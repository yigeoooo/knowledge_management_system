"""Page authorization and identity serialization use cases."""

from flask import g

from ..core.errors import ApiError
from ..core.extensions import db
from ..entities import Page, RolePagePermission


def accessible_pages(user):
    query = db.select(Page).where(Page.status == "active")
    if user.role.code != "super_admin":
        query = query.join(RolePagePermission).where(
            RolePagePermission.role_id == user.role_id,
            RolePagePermission.can_view.is_(True),
        )
    return db.session.scalars(query.order_by(Page.sort_order, Page.id)).all()


def has_page_access(*paths):
    if g.user.role.code == "super_admin":
        return True
    return db.session.scalar(
        db.select(Page.id)
        .join(RolePagePermission)
        .where(
            RolePagePermission.role_id == g.user.role_id,
            RolePagePermission.can_view.is_(True),
            Page.status == "active",
            Page.page_type != "button",
            Page.route_path.in_(paths),
        )
        .limit(1)
    ) is not None


def require_page_access(*paths):
    if not has_page_access(*paths):
        raise ApiError("没有访问此功能的权限", 403, 40301)


def identity(user):
    pages = accessible_pages(user)
    return {
        "user": {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role.code,
            "role_name": user.role.name,
        },
        "pages": [
            {
                "code": page.code,
                "name": page.name,
                "route_path": page.route_path,
                "route_name": page.route_name,
                "component_key": page.component_key,
                "parent_id": str(page.parent_id) if page.parent_id else None,
                "page_type": page.page_type,
                "sort_order": page.sort_order,
                "is_visible": page.is_visible,
            }
            for page in pages
        ],
    }


def ensure_active(user):
    if not user or user.status != "active" or user.role.status != "active":
        raise ApiError("账号或角色已停用，请联系管理员", 401, 40102)


__all__ = ["accessible_pages", "ensure_active", "has_page_access", "identity", "require_page_access"]
