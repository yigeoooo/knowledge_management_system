"""Role management for access-control roles."""

from uuid import uuid4

from flask import Blueprint, g, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from .auth import page_required
from .extensions import db
from .http import ApiError, status_filter, success
from .models import AuditLog, Role, RolePagePermission, User

roles = Blueprint("roles", __name__, url_prefix="/api/v1/roles")
EDITABLE_FIELDS = {"code", "name", "description", "status", "is_system"}
ROLE_STATUSES = {"active", "disabled"}


def role_data(role, user_count=None):
    result = {
        "id": str(role.id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "status": role.status,
        "created_at": role.created_at.isoformat(),
        "updated_at": role.updated_at.isoformat(),
    }
    if user_count is not None:
        result["user_count"] = user_count
    return result


def find_role(role_id, *, lock=False):
    query = db.select(Role).where(Role.id == role_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    role = db.session.scalar(query)
    if role is None:
        raise ApiError("角色不存在", 404, 40401)
    return role


def valid_text(value, label, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ApiError(f"{label}需为 1–{maximum} 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApiError(f"{label}不能包含控制字符", 422)
    return value


def valid_description(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > 2000:
        raise ApiError("角色描述不能超过 2000 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 and character not in "\r\n\t" for character in value):
        raise ApiError("角色描述不能包含控制字符", 422)
    return value or None


def validated_input(*, creating=False, current=None):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body:
        raise ApiError("请提交角色信息", 422)
    if set(body) - EDITABLE_FIELDS:
        raise ApiError("请求包含不支持的角色字段", 422)
    if creating and not {"code", "name"} <= body.keys():
        raise ApiError("请填写角色编码和角色名称", 422)

    values = {}
    if "code" in body:
        code = valid_text(body["code"], "角色编码", 50).lower()
        if not code[0].isalpha() or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in code
        ):
            raise ApiError("角色编码只能包含小写字母、数字、下划线或连字符，且必须以字母开头", 422)
        values["code"] = code
    if "name" in body:
        values["name"] = valid_text(body["name"], "角色名称", 100)
    if "description" in body:
        values["description"] = valid_description(body["description"])
    if "is_system" in body or creating:
        is_system = body.get("is_system", False)
        if not isinstance(is_system, bool):
            raise ApiError("角色类型必须是布尔值", 422)
        values["is_system"] = is_system
    if "status" in body or creating:
        status = body.get("status", "active")
        if status not in ROLE_STATUSES:
            raise ApiError("角色状态只能为启用或停用", 422)
        values["status"] = status

    if current is not None and current.code == "super_admin":
        if values.get("code", current.code) != current.code:
            raise ApiError("super_admin 角色的编码不能修改", 403, 40301)
        if values.get("is_system", current.is_system) is not True:
            raise ApiError("super_admin 角色必须保留为系统角色", 403, 40301)
        if values.get("status", current.status) != "active":
            raise ApiError("super_admin 角色不能停用", 403, 40301)
    return values


def ensure_unique_code(code, role_id=None):
    existing = db.session.scalar(db.select(Role).where(Role.code == code))
    if existing is not None and existing.id != role_id:
        raise ApiError("角色编码已被使用，请更换编码", 409, 40901)


def record_action(action, target, detail):
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action=action,
            resource_type="role",
            resource_id=target.id,
            ip_address=request.remote_addr,
            detail=detail,
        )
    )


def commit_role_change():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("角色信息存在冲突，请刷新后重试或更换角色编码", 409, 40901) from None


@roles.get("")
@page_required("/roles", "/role-permissions")
def list_roles():
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "20"))
    except ValueError:
        raise ApiError("分页参数必须是整数", 422) from None
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError("页码需大于 0，每页条数需在 1–100 之间", 422)
    keyword = request.args.get("q", "").strip()
    status = status_filter()
    if len(keyword) > 100 or "\x00" in keyword:
        raise ApiError("角色关键词不能超过 100 个字符或包含空字符", 422)
    if status not in {"", *ROLE_STATUSES}:
        raise ApiError("角色状态只能为启用或停用", 422)

    query = db.select(Role)
    if keyword:
        query = query.where(
            or_(
                Role.name.icontains(keyword, autoescape=True),
                Role.code.icontains(keyword, autoescape=True),
            )
        )
    if status:
        query = query.where(Role.status == status)
    # SelectPagination uses scalars(), so paginate roles separately and batch the page counts.
    result = db.paginate(
        query.order_by(Role.is_system.desc(), Role.created_at, Role.id),
        page=page,
        per_page=page_size,
        error_out=False,
    )
    role_ids = [role.id for role in result.items]
    counts = {}
    if role_ids:
        counts = dict(
            db.session.execute(
                db.select(User.role_id, func.count(User.id))
                .where(User.role_id.in_(role_ids))
                .group_by(User.role_id)
            ).all()
        )
    return success(
        {
            "items": [role_data(role, counts.get(role.id, 0)) for role in result.items],
            "total": result.total,
            "page": page,
            "page_size": page_size,
        }
    )


@roles.get("/<uuid:role_id>")
@page_required("/roles", "/role-permissions")
def role_detail(role_id):
    role = find_role(role_id)
    user_count = db.session.scalar(db.select(func.count(User.id)).where(User.role_id == role.id))
    return success(role_data(role, user_count))


@roles.post("")
@page_required("/roles")
def create_role():
    values = validated_input(creating=True)
    ensure_unique_code(values["code"])
    role = Role(id=uuid4(), **values)
    db.session.add(role)
    record_action(
        "role.create",
        role,
        {
            "code": role.code,
            "name": role.name,
            "is_system": role.is_system,
            "status": role.status,
        },
    )
    commit_role_change()
    return success(role_data(role, 0)), 201


@roles.put("/<uuid:role_id>")
@page_required("/roles")
def update_role(role_id):
    role = find_role(role_id, lock=True)
    values = validated_input(current=role)
    if "code" in values:
        ensure_unique_code(values["code"], role.id)
    changes = {
        field: {"before": getattr(role, field), "after": value}
        for field, value in values.items()
        if getattr(role, field) != value
    }
    for field, value in values.items():
        setattr(role, field, value)
    if changes:
        record_action("role.update", role, {"changes": changes})
    commit_role_change()
    user_count = db.session.scalar(db.select(func.count(User.id)).where(User.role_id == role.id))
    return success(role_data(role, user_count))


@roles.delete("/<uuid:role_id>")
@page_required("/roles")
def delete_role(role_id):
    role = find_role(role_id, lock=True)
    deleted_id = str(role.id)
    if role.code == "super_admin":
        raise ApiError("super_admin 角色不能删除", 403, 40301)
    assigned = db.session.scalar(db.select(func.count(User.id)).where(User.role_id == role.id))
    if assigned:
        raise ApiError("角色仍被用户使用，请先调整用户角色后再删除", 409, 40901)
    db.session.execute(
        db.delete(RolePagePermission).where(RolePagePermission.role_id == role.id)
    )
    record_action("role.delete", role, {"code": role.code, "name": role.name})
    db.session.delete(role)
    commit_role_change()
    return success({"id": deleted_id})
