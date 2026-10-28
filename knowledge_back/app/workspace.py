from datetime import datetime
from uuid import UUID

from flask import Blueprint, g, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from .auth import (
    accessible_pages,
    authenticated,
    has_page_access,
    page_required,
    require_page_access,
)
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
from .pdf_text import readable_answer
from .resource_operators import operator_names
from .storage import StorageError, ensure_bucket, knowledge_base_bucket

workspace = Blueprint("workspace", __name__, url_prefix="/api/v1")


def _qa_requester_name(log):
    source = (log.source_type or "").upper()
    if source == "WEB":
        return log.user.display_name if log.user and log.user.display_name else "未知用户"
    if source == "ROBOT":
        return (log.robot.name or log.robot.serial_no) if log.robot else "未知机器人"
    return "—"


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
    if isinstance(row, QALog):
        result["requester_name"] = _qa_requester_name(row)
    if isinstance(row, AuditLog):
        result["user_name"] = (
            row.operator.display_name or row.operator.username
            if row.operator else ("系统" if row.user_id is None else "未知用户")
        )
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


def _knowledge_base_data(base, operators=None):
    return {
        **(operators if operators is not None else operator_names([base], "knowledge_base")[base.id]),
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
@authenticated
def resource_list(resource):
    if resource not in RESOURCES:
        raise ApiError("资源不存在", 404, 40401)
    if resource == "pages":
        require_page_access("/pages", "/role-permissions")
    else:
        require_page_access(f"/{resource}")
    model, fields, search_field = RESOURCES[resource]
    page = request.args.get("page", 1, type=int)
    size = request.args.get("page_size", 20, type=int)
    if page < 1 or not 1 <= size <= 100:
        raise ApiError("分页参数不正确", 422)
    query = db.select(model)
    if model is AuditLog:
        query = query.options(joinedload(AuditLog.operator))
    elif model is QALog:
        query = query.options(joinedload(QALog.user), joinedload(QALog.robot))
        source_type = request.args.get("source_type", "").strip().upper()
        if source_type not in {"", "WEB", "ROBOT"}:
            raise ApiError("问题来源只能为 WEB 或 ROBOT", 422)
        if source_type:
            query = query.where(func.upper(QALog.source_type) == source_type)
    keyword = request.args.get("q", "").strip()[:200]
    if keyword:
        query = query.where(getattr(model, search_field).icontains(keyword, autoescape=True))
    status = status_filter()
    if status and hasattr(model, "status"):
        query = query.where(model.status == status)
    order = model.sort_order if model is Page else model.created_at.desc()
    pagination = db.paginate(query.order_by(order), page=page, per_page=size, error_out=False)
    names = operator_names(pagination.items, "document") if resource == "documents" else {}
    return success(
        {
            "items": [{**serialized(row, fields), **names.get(row.id, {})} for row in pagination.items],
            "total": pagination.total,
            "page": page,
            "page_size": size,
        }
    )


def _qa_log_data(log):
    from .retrieval import with_preview_urls
    knowledge_base = db.session.get(KnowledgeBase, log.knowledge_base_id)
    user = log.user
    robot = log.robot
    sources = with_preview_urls(log.sources) if isinstance(log.sources, list) else []
    return {
        "id": str(log.id),
        "request_id": log.request_id,
        "source_type": log.source_type,
        "requester_name": _qa_requester_name(log),
        "user_id": str(log.user_id) if log.user_id else None,
        "user_name": user.display_name if user else None,
        "robot_id": str(log.robot_id) if log.robot_id else None,
        "robot_name": robot.name if robot else None,
        "robot_serial_no": robot.serial_no if robot else None,
        "knowledge_base_id": str(log.knowledge_base_id),
        "knowledge_base_name": knowledge_base.name if knowledge_base else None,
        "question": log.question,
        "answer": readable_answer(log.answer, sources),
        "sources": sources,
        "retrieval_count": log.retrieval_count,
        "model_name": log.model_name,
        "status": log.status,
        "error_message": log.error_message,
        "latency_ms": log.latency_ms,
        "created_at": log.created_at.isoformat(),
        "updated_at": log.updated_at.isoformat(),
    }


@workspace.get("/qa-logs/<uuid:log_id>")
@page_required("/qa-logs")
def qa_log_detail(log_id):
    log = db.session.get(QALog, log_id)
    if log is None:
        raise ApiError("问答日志不存在", 404, 40401)
    return success(_qa_log_data(log))


@workspace.get("/roles/<uuid:role_id>/pages")
@page_required("/role-permissions")
def role_pages(role_id):
    role = db.session.get(Role, role_id)
    if role is None:
        raise ApiError("角色不存在", 404, 40401)
    if role.code == "super_admin":
        ids = db.session.scalars(
            db.select(Page.id).where(Page.status == "active").order_by(Page.sort_order, Page.id)
        ).all()
        return success({"page_ids": [str(page_id) for page_id in ids]})
    ids = db.session.scalars(
        db.select(RolePagePermission.page_id)
        .join(Page, Page.id == RolePagePermission.page_id)
        .where(
            RolePagePermission.role_id == role_id,
            RolePagePermission.can_view.is_(True),
        )
        .order_by(Page.sort_order, Page.id)
    ).all()
    return success({"page_ids": [str(value) for value in ids]})


def _role_page_ids():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"page_ids"}:
        raise ApiError("请求必须包含 page_ids 字段", 422)
    page_ids = body["page_ids"]
    if not isinstance(page_ids, list):
        raise ApiError("page_ids 必须是数组", 422)

    parsed = []
    seen = set()
    for value in page_ids:
        if not isinstance(value, str):
            raise ApiError("页面 ID 必须是 UUID 字符串", 422)
        try:
            page_id = UUID(value)
        except (ValueError, AttributeError):
            raise ApiError("页面 ID 格式不正确", 422) from None
        if page_id in seen:
            raise ApiError("page_ids 不能包含重复页面", 422)
        seen.add(page_id)
        parsed.append(page_id)

    if parsed:
        existing = set(
            db.session.scalars(db.select(Page.id).where(Page.id.in_(parsed))).all()
        )
        missing = [str(page_id) for page_id in parsed if page_id not in existing]
        if missing:
            raise ApiError("页面不存在或已删除", 422)
    return parsed


@workspace.put("/roles/<uuid:role_id>/pages")
@page_required("/role-permissions")
def update_role_pages(role_id):
    role = db.session.scalar(
        db.select(Role)
        .where(Role.id == role_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if role is None:
        raise ApiError("角色不存在", 404, 40401)
    page_ids = _role_page_ids()

    # Keep the built-in administrator usable even when a stale client submits an
    # incomplete selection. Disabled pages may be retained, but every active
    # page must remain available to this role.
    if role.code == "super_admin":
        active_page_ids = set(
            db.session.scalars(db.select(Page.id).where(Page.status == "active")).all()
        )
        if not active_page_ids.issubset(page_ids):
            raise ApiError("super_admin 必须保留全部启用页面权限", 403, 40301)

    current_ids = set(
        db.session.scalars(
            db.select(RolePagePermission.page_id).where(
                RolePagePermission.role_id == role.id,
                RolePagePermission.can_view.is_(True),
            )
        ).all()
    )
    requested_ids = set(page_ids)
    db.session.execute(
        db.delete(RolePagePermission).where(RolePagePermission.role_id == role.id)
    )
    db.session.add_all(
        [
            RolePagePermission(role_id=role.id, page_id=page_id, can_view=True)
            for page_id in page_ids
        ]
    )
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action="role.permissions.update",
            resource_type="role",
            resource_id=role.id,
            ip_address=request.remote_addr,
            detail={
                "before_page_ids": sorted(str(page_id) for page_id in current_ids),
                "after_page_ids": sorted(str(page_id) for page_id in requested_ids),
            },
        )
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("页面权限保存失败，请刷新后重试", 409, 40901) from None

    ids = db.session.scalars(
        db.select(RolePagePermission.page_id)
        .join(Page, Page.id == RolePagePermission.page_id)
        .where(
            RolePagePermission.role_id == role.id,
            RolePagePermission.can_view.is_(True),
        )
        .order_by(Page.sort_order, Page.id)
    ).all()
    return success({"role_id": str(role.id), "page_ids": [str(value) for value in ids]})


@workspace.get("/knowledge-bases")
@page_required("/knowledge-bases", "/documents", "/create-document", "/qa")
def knowledge_bases():
    # 获得知识库管理权限的角色可查看全部状态；其他客户端只读取可用知识库。
    can_manage = has_page_access("/knowledge-bases")
    if not can_manage:
        bases = db.session.scalars(
            db.select(KnowledgeBase)
            .where(KnowledgeBase.status == "active")
            .order_by(KnowledgeBase.created_at, KnowledgeBase.id)
        ).all()
        names = operator_names(bases, "knowledge_base")
        return success({"items": [_knowledge_base_data(base, names[base.id]) for base in bases]})

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
    names = operator_names(result.items, "knowledge_base")
    return success(
        {
            "items": [_knowledge_base_data(base, names[base.id]) for base in result.items],
            "total": result.total,
            "page": page,
            "page_size": page_size,
        }
    )


@workspace.get("/knowledge-bases/<uuid:knowledge_base_id>")
@page_required("/knowledge-bases", "/documents", "/create-document", "/qa")
def knowledge_base_detail(knowledge_base_id):
    base = _find_knowledge_base(knowledge_base_id)
    if not has_page_access("/knowledge-bases") and base.status != "active":
        raise ApiError("知识库不存在", 404, 40401)
    return success(_knowledge_base_data(base))


@workspace.post("/knowledge-bases")
@page_required("/knowledge-bases")
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
@page_required("/knowledge-bases")
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
@page_required("/knowledge-bases")
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
@page_required("/dashboard")
def dashboard():
    paths = {page.route_path for page in accessible_pages(g.user)}
    metrics = [
        ("knowledge_base_count", "/knowledge-bases", KnowledgeBase,
         [KnowledgeBase.status == "active"]),
        ("user_count", "/users", User, [User.status != "deleted"]),
        ("role_count", "/roles", Role, []),
        ("page_count", "/pages", Page, []),
        ("document_count", "/documents", Document, []),
        ("robot_count", "/robots", Robot, []),
    ]
    return success({
        key: db.session.scalar(db.select(db.func.count()).select_from(model).where(*filters))
        for key, path, model, filters in metrics if path in paths
    })
