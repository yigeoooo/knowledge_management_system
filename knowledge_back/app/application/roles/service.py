"""Role management use-case helpers."""

from flask import g, request
from sqlalchemy.exc import IntegrityError

from ...core.errors import ApiError
from ...core.extensions import db
from ...entities import AuditLog
from ...repositories.identity_repository import RoleRepository

EDITABLE_FIELDS = {"code", "name", "description", "status", "is_system"}
ROLE_STATUSES = {"active", "disabled"}
role_repository = RoleRepository()

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
    role = role_repository.find(role_id, lock=lock)
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
    existing = role_repository.find_by_code(code)
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

