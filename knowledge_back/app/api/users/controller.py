"""Administrator user management; deleted accounts retain historical relationships."""

import secrets
from uuid import uuid4

from flask import Blueprint, g, request
from sqlalchemy.orm import selectinload

from ...application.users.service import (
    commit_user_change,
    ensure_unique_username,
    find_user,
    protected_change,
    record_action,
    revoke_sessions,
    user_data,
    validated_input,
)
from ...core.extensions import db
from ...core.http import ApiError, status_filter, success
from ...entities import Role, User
from ..auth.controller import page_required, password_hasher

users = Blueprint("users", __name__, url_prefix="/api/v1/users")



@users.get("")
@page_required("/users")
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
@page_required("/users")
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
@page_required("/users")
def user_detail(user_id):
    return success(user_data(find_user(user_id)))


@users.post("")
@page_required("/users")
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
@page_required("/users")
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
@page_required("/users")
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
