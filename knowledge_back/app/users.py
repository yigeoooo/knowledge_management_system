"""Administrator user management; deleted accounts retain historical relationships."""

import secrets
from uuid import UUID, uuid4

from flask import Blueprint, g, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .auth import password_hasher
from .extensions import db
from .http import ApiError, status_filter, success
from .models import AuditLog, Role, User, UserSession, now
from .workspace import admin_only

users = Blueprint("users", __name__, url_prefix="/api/v1/users")
EDITABLE_FIELDS = {"username", "display_name", "role_id", "status", "password"}


def user_data(user):
    # Password fields are intentionally excluded from every management response.
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role_id": str(user.role_id),
        "role_code": user.role.code,
        "role_name": user.role.name,
        "status": user.status,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def find_user(user_id, *, lock=False):
    query = db.select(User).where(User.id == user_id, User.status != "deleted")
    if lock:
        # Authentication may already have loaded this same user in the identity map.
        query = query.with_for_update().execution_options(populate_existing=True)
    user = db.session.scalar(query)
    if user is None:
        raise ApiError("用户不存在或已删除", 404, 40401)
    return user


def valid_text(value, label, maximum=100):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ApiError(f"{label}需为 1–{maximum} 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApiError(f"{label}不能包含控制字符", 422)
    return value


def validated_input(*, creating=False, current=None):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body:
        raise ApiError("请提交用户信息", 422)
    if set(body) - EDITABLE_FIELDS:
        raise ApiError("请求包含不支持的用户字段", 422)
    if creating and not {"username", "display_name", "role_id", "password"} <= body.keys():
        raise ApiError("请填写用户名、显示名称、角色和初始密码", 422)

    values = {}
    if "username" in body:
        values["username"] = valid_text(body["username"], "用户名")
        if any(character.isspace() for character in values["username"]):
            raise ApiError("用户名不能包含空格", 422)
    if "display_name" in body:
        values["display_name"] = valid_text(body["display_name"], "显示名称")
    if "status" in body or creating:
        values["status"] = body.get("status", "active")
        if values["status"] not in ("active", "disabled"):
            raise ApiError("用户状态只能为启用或停用", 422)
    if "role_id" in body:
        try:
            role_id = UUID(body["role_id"])
        except (ValueError, TypeError, AttributeError):
            raise ApiError("请选择有效角色", 422) from None
        role = db.session.get(Role, role_id)
        if role is None or (role.status != "active" and (creating or current.role_id != role_id)):
            raise ApiError("所选角色不存在或已停用", 422)
        values["role_id"] = role_id
    if "password" in body:
        password = body["password"]
        if not isinstance(password, str) or "\x00" in password:
            raise ApiError("密码格式不正确", 422)
        if password or creating:
            if not 12 <= len(password) <= 1024:
                raise ApiError("密码需为 12–1024 个字符", 422)
            values["password"] = password
    return values


def ensure_unique_username(username, user_id=None):
    existing = db.session.scalar(db.select(User).where(User.username == username))
    if existing is not None and existing.id != user_id:
        raise ApiError("用户名已被使用（包括已删除账号），请更换用户名", 409, 40901)


def commit_user_change():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Handles the race where another request claimed the username after validation.
        raise ApiError("用户信息存在冲突，请刷新后重试或更换用户名", 409, 40901) from None


def record_action(action, target, detail):
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action=action,
            resource_type="user",
            resource_id=target.id,
            ip_address=request.remote_addr,
            detail=detail,
        )
    )


def revoke_sessions(user):
    # Leave pending user writes for commit_user_change's uniqueness error handling.
    with db.session.no_autoflush:
        db.session.execute(
            db.update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now())
        )


def protected_change(user, values):
    if user.username == "root":
        if values.get("username", user.username) != "root":
            raise ApiError("Root 管理员的用户名不能修改", 403, 40301)
        if values.get("role_id", user.role_id) != user.role_id:
            raise ApiError("Root 管理员的角色不能修改", 403, 40301)
        if values.get("status", user.status) != "active":
            raise ApiError("Root 管理员不能停用", 403, 40301)
    if user.id == g.user.id:
        if values.get("role_id", user.role_id) != user.role_id:
            raise ApiError("不能修改当前登录账号的角色，请由其他管理员操作", 403, 40301)
        if values.get("status", user.status) != "active":
            raise ApiError("不能停用当前登录账号", 403, 40301)


@users.get("")
@admin_only
def list_users():
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
        raise ApiError("显示名称关键词不能超过 100 个字符或包含空字符", 422)
    if status not in ("", "active", "disabled"):
        raise ApiError("用户状态只能为启用或停用", 422)
    query = db.select(User).options(selectinload(User.role)).where(User.status != "deleted")
    if keyword:
        query = query.where(User.display_name.icontains(keyword, autoescape=True))
    if status:
        query = query.where(User.status == status)
    result = db.paginate(
        query.order_by(User.created_at.desc(), User.id),
        page=page,
        per_page=page_size,
        error_out=False,
    )
    return success(
        {
            "items": [user_data(user) for user in result.items],
            "total": result.total,
            "page": page,
            "page_size": page_size,
        }
    )


@users.get("/role-options")
@admin_only
def role_options():
    roles = db.session.scalars(db.select(Role).order_by(Role.created_at, Role.id)).all()
    return success(
        {
            "items": [
                {"id": str(r.id), "name": r.name, "code": r.code, "status": r.status} for r in roles
            ]
        }
    )


@users.get("/<uuid:user_id>")
@admin_only
def user_detail(user_id):
    return success(user_data(find_user(user_id)))


@users.post("")
@admin_only
def create_user():
    values = validated_input(creating=True)
    ensure_unique_username(values["username"])
    password = values.pop("password")
    user = User(
        id=uuid4(),
        **values,
        password_hash=password_hasher.hash(password),
        password_plaintext=password,
    )
    db.session.add(user)
    record_action(
        "user.create",
        user,
        {"username": user.username, "role_id": str(user.role_id), "status": user.status},
    )
    commit_user_change()
    return success(user_data(user)), 201


@users.put("/<uuid:user_id>")
@admin_only
def update_user(user_id):
    user = find_user(user_id, lock=True)
    values = validated_input(current=user)
    protected_change(user, values)
    if "username" in values:
        ensure_unique_username(values["username"], user.id)
    password = values.pop("password", None)
    changes = {
        field: {"before": str(getattr(user, field)), "after": str(value)}
        for field, value in values.items()
        if getattr(user, field) != value
    }
    should_revoke = bool(password) or any(
        field in changes for field in ("username", "role_id", "status")
    )
    for field, value in values.items():
        setattr(user, field, value)
    if password:
        user.password_hash = password_hasher.hash(password)
        user.password_plaintext = password
    if should_revoke:
        revoke_sessions(user)
    if changes or password:
        record_action("user.update", user, {"changes": changes, "password_changed": bool(password)})
    commit_user_change()
    return success(
        {"user": user_data(user), "reauthenticate": should_revoke and user.id == g.user.id}
    )


@users.delete("/<uuid:user_id>")
@admin_only
def delete_user(user_id):
    user = find_user(user_id, lock=True)
    if user.username == "root" or user.id == g.user.id:
        raise ApiError("不能删除 Root 管理员或当前登录账号", 403, 40301)
    user.status = "deleted"
    user.password_plaintext = None
    user.password_hash = password_hasher.hash(secrets.token_urlsafe(48))
    revoke_sessions(user)
    record_action(
        "user.delete", user, {"username": user.username, "display_name": user.display_name}
    )
    commit_user_change()
    return success({"id": str(user.id)})
