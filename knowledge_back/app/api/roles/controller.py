"""Role management for access-control roles."""

from uuid import uuid4

from flask import Blueprint, request
from sqlalchemy import func, or_

from ...application.roles.service import (
    ROLE_STATUSES,
    commit_role_change,
    ensure_unique_code,
    find_role,
    record_action,
    role_data,
    validated_input,
)
from ...core.extensions import db
from ...core.http import ApiError, status_filter, success
from ...entities import Role, RolePagePermission, User
from ..auth.controller import page_required

roles = Blueprint("roles", __name__, url_prefix="/api/v1/roles")

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
