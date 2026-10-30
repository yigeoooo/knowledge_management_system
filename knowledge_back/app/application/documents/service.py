"""Document use-case helpers and persistence orchestration."""

import mimetypes
from pathlib import PurePath
from uuid import UUID

from flask import current_app, g, request
from sqlalchemy import func

from ...application.audit.operator_service import operator_names
from ...core.errors import ApiError
from ...core.extensions import db
from ...entities import AuditLog, Document, DocumentVersion, IndexTask, KnowledgeBase
from ...integrations.storage.minio_adapter import StorageError

DOCUMENT_STATUSES = {"active", "archived"}
VERSION_STATUSES = {"PENDING_UPLOAD", "UPLOADED", "PROCESSING", "EMBEDDING", "INDEXED", "FAILED", "ARCHIVED"}
TASK_STATUSES = {"PENDING", "RUNNING", "SUCCESS", "FAILED"}
ALLOWED_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
}
TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
EXCEL_EXTENSIONS = {".xls", ".xlsx"}
PREVIEWABLE_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".mov"} | EXCEL_EXTENSIONS
CONTENT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
}


def _api_storage(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except StorageError as error:
        raise ApiError(str(error), 503, 50301) from error


def _schedule_index_task():
    """Wake the in-process worker after a task is committed.

    The standalone ``index-worker`` command remains available for production
    deployments and recovery.  Local development and the web UI should not
    require a second terminal just to process a newly uploaded document.
    """

    if current_app.config.get("INDEX_WORKER_AUTOSTART", True):
        from ...workers.index_worker import schedule_worker

        schedule_worker(current_app._get_current_object())


def _uuid(value, label):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ApiError(f"{label}格式不正确", 422) from None


def _text(value, label, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ApiError(f"{label}需为 1–{maximum} 个字符", 422)
    value = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApiError(f"{label}不能包含控制字符", 422)
    return value


def _filename(value):
    value = _text(value, "文件名", 255)
    value = PurePath(value.replace("\\", "/")).name
    if not value or value.startswith(".") and value.count(".") == 1:
        raise ApiError("文件名不正确", 422)
    if PurePath(value).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ApiError("文件类型不受支持，请上传 Markdown、PDF、Word、Excel、图片或视频文件", 422, 42202)
    return value


def _description(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > 2000:
        raise ApiError("描述不能超过 2000 个字符", 422)
    return value.strip() or None


def _document_data(document, *, include_versions=False, operators=None):
    result = {
        **(operators if operators is not None else operator_names([document], "document")[document.id]),
        "id": str(document.id),
        "knowledge_base_id": str(document.knowledge_base_id),
        "title": document.title,
        "status": document.status,
        "current_version_id": str(document.current_version_id) if document.current_version_id else None,
        "created_by": str(document.created_by) if document.created_by else None,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }
    if include_versions:
        versions = db.session.scalars(
            db.select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_no.desc(), DocumentVersion.created_at.desc())
        ).all()
        result["versions"] = [_version_data(version) for version in versions]
    return result


def _version_data(version):
    latest_task = db.session.scalar(
        db.select(IndexTask)
        .where(IndexTask.document_version_id == version.id)
        .order_by(IndexTask.created_at.desc(), IndexTask.id.desc())
    )
    return {
        "id": str(version.id),
        "document_id": str(version.document_id),
        "version_no": version.version_no,
        "filename": version.filename,
        "content_type": version.content_type,
        "file_size": version.file_size,
        "content_hash": version.content_hash,
        "status": version.status,
        "chunk_count": version.chunk_count,
        "embedding_model": version.embedding_model,
        "error_message": version.error_message,
        "task": _task_data(latest_task) if latest_task else None,
        "created_by": str(version.created_by) if version.created_by else None,
        "created_at": version.created_at.isoformat(),
        "updated_at": version.updated_at.isoformat(),
    }


def _task_data(task):
    return {
        "id": str(task.id),
        "document_version_id": str(task.document_version_id),
        "task_type": task.task_type,
        "status": task.status,
        "attempts": task.attempts,
        "error_message": task.error_message,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "created_at": task.created_at.isoformat(),
    }


def _find_knowledge_base(knowledge_base_id, *, lock=False):
    query = db.select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
    if lock:
        query = query.with_for_update()
    base = db.session.scalar(query)
    if base is None:
        raise ApiError("知识库不存在", 404, 40401)
    if base.status != "active":
        raise ApiError("知识库已停用或归档，不能管理文档", 409, 40901)
    return base


def _find_document(document_id, *, knowledge_base_id=None, lock=False, include_archived=False):
    query = db.select(Document).where(Document.id == document_id)
    if knowledge_base_id is not None:
        query = query.where(Document.knowledge_base_id == knowledge_base_id)
    if not include_archived:
        query = query.where(Document.status == "active")
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    document = db.session.scalar(query)
    if document is None:
        raise ApiError("文档不存在或已归档", 404, 40401)
    return document


def _find_version(version_id, *, document_id=None, lock=False):
    query = db.select(DocumentVersion).where(DocumentVersion.id == version_id)
    if document_id is not None:
        query = query.where(DocumentVersion.document_id == document_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    version = db.session.scalar(query)
    if version is None:
        raise ApiError("文档版本不存在", 404, 40401)
    return version


def _record(action, document, detail):
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action=action,
            resource_type="document",
            resource_id=document.id,
            ip_address=request.remote_addr,
            detail=detail,
        )
    )


def _next_version(document_id):
    current = db.session.scalar(
        db.select(func.coalesce(func.max(DocumentVersion.version_no), 0)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return int(current or 0) + 1


def _max_document_size():
    from flask import current_app

    return current_app.config["MAX_DOCUMENT_SIZE"]


def _validate_upload_body(body):
    if not isinstance(body, dict):
        raise ApiError("请提交上传信息", 422)
    allowed = {"knowledge_base_id", "document_id", "base_version_id", "filename", "title", "file_size", "content_type"}
    if set(body) - allowed:
        raise ApiError("请求包含不支持的上传字段", 422)
    knowledge_base_id = _uuid(body.get("knowledge_base_id"), "知识库 ID")
    filename = _filename(body.get("filename"))
    try:
        file_size = int(body.get("file_size"))
    except (ValueError, TypeError):
        raise ApiError("文件大小不正确", 422, 42202) from None
    if not 1 <= file_size <= _max_document_size():
        raise ApiError(f"文件大小需在 1 字节至 {_max_document_size()} 字节之间", 422, 42202)
    title = body.get("title")
    title = _text(title, "文档标题", 255) if title is not None else PurePath(filename).stem
    document_id = _uuid(body["document_id"], "文档 ID") if body.get("document_id") else None
    base_version_id = _uuid(body["base_version_id"], "基础版本 ID") if body.get("base_version_id") else None
    extension = PurePath(filename).suffix.lower()
    expected_content_type = CONTENT_TYPES[extension]
    supplied_content_type = body.get("content_type")
    if supplied_content_type is not None and (
        not isinstance(supplied_content_type, str)
        or len(supplied_content_type) > 100
        or any(ord(character) < 32 or ord(character) == 127 for character in supplied_content_type)
    ):
        raise ApiError("文件类型不正确", 422, 42202)
    # The browser supplied value is advisory.  Persist a canonical type derived
    # from the allow-listed extension so preview/download headers cannot be
    # changed to an unrelated active content type.
    content_type = expected_content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return knowledge_base_id, filename, file_size, title, document_id, base_version_id, content_type

