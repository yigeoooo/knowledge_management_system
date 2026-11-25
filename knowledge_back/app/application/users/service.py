"""User management use-case helpers.

The HTTP controller owns route declarations and response formatting; this
module owns user validation, identity lookup, auditing, and session revocation.
"""

from uuid import UUID

from flask import g, request
from sqlalchemy.exc import IntegrityError

from ...core.errors import ApiError
from ...core.extensions import db
from ...entities import AuditLog, Role, UserSession, now
from ...repositories.identity_repository import UserRepository

EDITABLE_FIELDS = {"username", "display_name", "role_id", "status", "password"}
user_repository = UserRepository()


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
    # Authentication may already have loaded this same user in the identity map.
    user = user_repository.find(user_id, lock=lock)
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
    existing = user_repository.find_any_by_username(username)
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

