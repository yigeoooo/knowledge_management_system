from datetime import datetime
from functools import wraps
from uuid import UUID

from flask import Blueprint, g, request

from .auth import authenticated
from .extensions import db
from .http import ApiError, success
from .models import (
    AuditLog,
    Document,
    KnowledgeBase,
    Page,
    QALog,
    Robot,
    Role,
    RolePagePermission,
    User,
)

workspace = Blueprint("workspace", __name__, url_prefix="/api/v1")


def admin_only(view):
    @authenticated
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user.role.code != "super_admin":
            raise ApiError("没有访问此功能的权限", 403, 40301)
        return view(*args, **kwargs)

    return wrapped


def serialized(row, fields):
    result = {}
    for field in fields:
        value = getattr(row, field)
        result[field] = (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
        )
    if isinstance(row, User):
        result["role_name"] = row.role.name
    return result


RESOURCES = {
    "roles": (
        Role,
        ["id", "code", "name", "description", "status", "is_system", "created_at"],
        "name",
    ),
    "pages": (
        Page,
        ["id", "code", "name", "route_path", "component_key", "page_type", "sort_order", "status"],
        "name",
    ),
    "documents": (
        Document,
        ["id", "title", "knowledge_base_id", "current_version_id", "status", "updated_at"],
        "title",
    ),
    "robots": (
        Robot,
        ["id", "serial_no", "name", "description", "status", "last_request_at"],
        "serial_no",
    ),
    "qa-logs": (
        QALog,
        ["id", "request_id", "question", "source_type", "status", "latency_ms", "created_at"],
        "question",
    ),
    "audit-logs": (
        AuditLog,
        ["id", "action", "resource_type", "resource_id", "user_id", "ip_address", "created_at"],
        "action",
    ),
}


@workspace.get("/<resource>")
@admin_only
def resource_list(resource):
    if resource not in RESOURCES:
        raise ApiError("资源不存在", 404, 40401)
    model, fields, search_field = RESOURCES[resource]
    page = request.args.get("page", 1, type=int)
    size = request.args.get("page_size", 20, type=int)
    if page < 1 or not 1 <= size <= 100:
        raise ApiError("分页参数不正确", 422)
    query = db.select(model)
    keyword = request.args.get("q", "").strip()[:200]
    if keyword:
        query = query.where(getattr(model, search_field).icontains(keyword, autoescape=True))
    status = request.args.get("status", "")
    if status and hasattr(model, "status"):
        query = query.where(model.status == status)
    order = model.sort_order if model is Page else model.created_at.desc()
    pagination = db.paginate(query.order_by(order), page=page, per_page=size, error_out=False)
    return success(
        {
            "items": [serialized(row, fields) for row in pagination.items],
            "total": pagination.total,
            "page": page,
            "page_size": size,
        }
    )


@workspace.get("/roles/<uuid:role_id>/pages")
@admin_only
def role_pages(role_id):
    if db.session.get(Role, role_id) is None:
        raise ApiError("角色不存在", 404, 40401)
    ids = db.session.scalars(
        db.select(RolePagePermission.page_id).where(
            RolePagePermission.role_id == role_id,
            RolePagePermission.can_view.is_(True),
        )
    ).all()
    return success({"page_ids": [str(value) for value in ids]})


@workspace.get("/knowledge-bases")
@authenticated
def knowledge_bases():
    bases = db.session.scalars(
        db.select(KnowledgeBase)
        .where(
            KnowledgeBase.status == "active",
        )
        .order_by(KnowledgeBase.created_at)
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(k.id),
                    "code": k.code,
                    "name": k.name,
                    "description": k.description,
                    "status": k.status,
                }
                for k in bases
            ]
        }
    )


@workspace.get("/dashboard")
@admin_only
def dashboard():
    return success(
        {
            "knowledge_base_count": db.session.scalar(
                db.select(db.func.count())
                .select_from(KnowledgeBase)
                .where(KnowledgeBase.status == "active")
            ),
            "user_count": db.session.scalar(
                db.select(db.func.count()).select_from(User).where(User.status != "deleted")
            ),
            "role_count": db.session.scalar(db.select(db.func.count()).select_from(Role)),
            "page_count": db.session.scalar(db.select(db.func.count()).select_from(Page)),
            "document_count": db.session.scalar(db.select(db.func.count()).select_from(Document)),
            "robot_count": db.session.scalar(db.select(db.func.count()).select_from(Robot)),
        }
    )
