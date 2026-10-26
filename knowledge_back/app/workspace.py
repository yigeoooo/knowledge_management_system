from datetime import datetime
from functools import wraps
from uuid import UUID

from flask import Blueprint, g, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .auth import authenticated
from .extensions import db
from .http import ApiError, status_filter, success
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
from .storage import StorageError, ensure_bucket, knowledge_base_bucket

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

KNOWLEDGE_BASE_STATUSES = {"active", "disabled", "archived"}
KNOWLEDGE_BASE_FIELDS = {"code", "name", "description", "status"}


def _knowledge_base_data(base):
    return {
        "id": str(base.id),
        "code": base.code,
        "name": base.name,
        "description": base.description,
        "status": base.status,
        "created_by": str(base.created_by) if base.created_by else None,
        "created_at": base.created_at.isoformat(),
        "updated_at": base.updated_at.isoformat(),
    }


def _knowledge_base_text(value, label, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ApiError(f"{label}需为 1–{maximum} 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApiError(f"{label}不能包含控制字符", 422)
    return value


def _knowledge_base_description(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > 2000:
        raise ApiError("知识库描述不能超过 2000 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 and character not in "\r\n\t" for character in value):
        raise ApiError("知识库描述不能包含控制字符", 422)
    return value or None


def _validated_knowledge_base_input(*, creating=False):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body:
        raise ApiError("请提交知识库信息", 422)
    if set(body) - KNOWLEDGE_BASE_FIELDS:
        raise ApiError("请求包含不支持的知识库字段", 422)
    if creating and not {"code", "name"} <= body.keys():
        raise ApiError("请填写知识库编码和名称", 422)

    values = {}
    if "code" in body:
        code = _knowledge_base_text(body["code"], "知识库编码", 100).lower()
        if not code[0].isalpha() or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in code
        ):
            raise ApiError("知识库编码只能包含小写字母、数字、下划线或连字符，且必须以字母开头", 422)
        values["code"] = code
    if "name" in body:
        values["name"] = _knowledge_base_text(body["name"], "知识库名称", 200)
    if "description" in body:
        values["description"] = _knowledge_base_description(body["description"])
    if "status" in body or creating:
        status = body.get("status", "active")
        if status not in KNOWLEDGE_BASE_STATUSES:
            raise ApiError("知识库状态只能为启用、停用或归档", 422)
        values["status"] = status
    return values


def _find_knowledge_base(knowledge_base_id, *, lock=False):
    query = db.select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    base = db.session.scalar(query)
    if base is None:
        raise ApiError("知识库不存在", 404, 40401)
    return base


def _ensure_unique_knowledge_base_code(code, knowledge_base_id=None):
    existing = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.code == code))
    if existing is not None and existing.id != knowledge_base_id:
        raise ApiError("知识库编码已被使用，请更换编码", 409, 40901)


def _record_knowledge_base_action(action, base, detail):
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action=action,
            resource_type="knowledge_base",
            resource_id=base.id,
            ip_address=request.remote_addr,
            detail=detail,
        )
    )


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
    status = status_filter()
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
    # 管理员需要查看全部状态；普通用户和问答客户端只能看到可用知识库。
    is_admin = g.user.role.code == "super_admin"
    if not is_admin:
        bases = db.session.scalars(
            db.select(KnowledgeBase)
            .where(KnowledgeBase.status == "active")
            .order_by(KnowledgeBase.created_at, KnowledgeBase.id)
        ).all()
        return success({"items": [_knowledge_base_data(base) for base in bases]})

    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "20"))
    except ValueError:
        raise ApiError("分页参数必须是整数", 422) from None
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError("页码需大于 0，每页条数需在 1–100 之间", 422)
    keyword = request.args.get("q", "").strip()
    status = status_filter()
    if len(keyword) > 200 or "\x00" in keyword:
        raise ApiError("知识库关键词不能超过 200 个字符或包含空字符", 422)
    if status not in {"", *KNOWLEDGE_BASE_STATUSES}:
        raise ApiError("知识库状态只能为启用、停用或归档", 422)
    query = db.select(KnowledgeBase)
    if keyword:
        query = query.where(
            or_(
                KnowledgeBase.name.icontains(keyword, autoescape=True),
                KnowledgeBase.code.icontains(keyword, autoescape=True),
            )
        )
    if status:
        query = query.where(KnowledgeBase.status == status)
    result = db.paginate(
        query.order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id),
        page=page,
        per_page=page_size,
        error_out=False,
    )
    return success(
        {
            "items": [_knowledge_base_data(base) for base in result.items],
            "total": result.total,
            "page": page,
            "page_size": page_size,
        }
    )


@workspace.get("/knowledge-bases/<uuid:knowledge_base_id>")
@authenticated
def knowledge_base_detail(knowledge_base_id):
    base = _find_knowledge_base(knowledge_base_id)
    if g.user.role.code != "super_admin" and base.status != "active":
        raise ApiError("知识库不存在", 404, 40401)
    return success(_knowledge_base_data(base))


@workspace.post("/knowledge-bases")
@admin_only
def create_knowledge_base():
    values = _validated_knowledge_base_input(creating=True)
    _ensure_unique_knowledge_base_code(values["code"])
    base = KnowledgeBase(created_by=g.user.id, **values)
    db.session.add(base)
    db.session.flush()
    # A successful response must represent a knowledge base that also exists
    # in object storage.  The bucket is stable across code/name edits because
    # it is derived from the immutable UUID.
    try:
        ensure_bucket(knowledge_base_bucket(base.id))
    except StorageError as error:
        db.session.rollback()
        raise ApiError(str(error), 503, 50301) from error
    _record_knowledge_base_action(
        "knowledge_base.create",
        base,
        {"code": base.code, "name": base.name, "status": base.status},
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("知识库信息存在冲突，请刷新后重试或更换编码", 409, 40901) from None
    return success(_knowledge_base_data(base)), 201


@workspace.put("/knowledge-bases/<uuid:knowledge_base_id>")
@admin_only
def update_knowledge_base(knowledge_base_id):
    base = _find_knowledge_base(knowledge_base_id, lock=True)
    values = _validated_knowledge_base_input()
    if "code" in values:
        _ensure_unique_knowledge_base_code(values["code"], base.id)
    changes = {
        field: {"before": getattr(base, field), "after": value}
        for field, value in values.items()
        if getattr(base, field) != value
    }
    for field, value in values.items():
        setattr(base, field, value)
    if changes:
        _record_knowledge_base_action("knowledge_base.update", base, {"changes": changes})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("知识库信息存在冲突，请刷新后重试或更换编码", 409, 40901) from None
    return success(_knowledge_base_data(base))


@workspace.delete("/knowledge-bases/<uuid:knowledge_base_id>")
@admin_only
def archive_knowledge_base(knowledge_base_id):
    base = _find_knowledge_base(knowledge_base_id, lock=True)
    if base.status != "archived":
        previous_status = base.status
        base.status = "archived"
        _record_knowledge_base_action(
            "knowledge_base.archive", base, {"previous_status": previous_status}
        )
        db.session.commit()
    return success(_knowledge_base_data(base))


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
