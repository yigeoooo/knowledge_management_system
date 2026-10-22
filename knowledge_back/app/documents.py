"""Knowledge-base document storage, versioning, and indexing task interfaces."""

import hashlib
import mimetypes
from io import BytesIO
from pathlib import PurePath
from uuid import UUID, uuid4

from flask import Blueprint, current_app, g, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .http import ApiError, success
from .models import AuditLog, Document, DocumentVersion, IndexTask, KnowledgeBase
from .storage import (
    StorageError,
    knowledge_base_bucket,
    presign_get,
    presign_put,
    put_object,
    read_object,
    stat_object,
)
from .workspace import admin_only

documents = Blueprint("documents", __name__, url_prefix="/api/v1")
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
PREVIEWABLE_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".mov"}
CONTENT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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
        from .indexer import schedule_worker

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
        raise ApiError("文件类型不受支持，请上传 Markdown、PDF、Word、图片或视频文件", 422, 42202)
    return value


def _description(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > 2000:
        raise ApiError("描述不能超过 2000 个字符", 422)
    return value.strip() or None


def _document_data(document, *, include_versions=False):
    result = {
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


@documents.get("/knowledge-bases/<uuid:knowledge_base_id>/documents")
@admin_only
def list_documents(knowledge_base_id):
    _find_knowledge_base(knowledge_base_id)
    # Also recover tasks left pending by a process restart.  The request only
    # wakes the queue consumer; all indexing work still happens in the worker
    # thread and the response remains fast.
    _schedule_index_task()
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "20"))
    except ValueError:
        raise ApiError("分页参数必须是整数", 422) from None
    if page < 1 or not 1 <= page_size <= 100:
        raise ApiError("页码需大于 0，每页条数需在 1–100 之间", 422)
    keyword = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    if len(keyword) > 200 or "\x00" in keyword:
        raise ApiError("文档关键词不能超过 200 个字符或包含空字符", 422)
    if status and status not in DOCUMENT_STATUSES:
        raise ApiError("文档状态不正确", 422)
    query = db.select(Document).where(Document.knowledge_base_id == knowledge_base_id)
    if keyword:
        query = query.where(Document.title.icontains(keyword, autoescape=True))
    if status:
        query = query.where(Document.status == status)
    result = db.paginate(
        query.order_by(Document.updated_at.desc(), Document.id),
        page=page,
        per_page=page_size,
        error_out=False,
    )
    items = []
    for document in result.items:
        current = db.session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
        # A newly uploaded version is intentionally not current until indexing
        # succeeds.  Still expose that latest version so the management page
        # can show PENDING/PROCESSING/FAILED instead of the document's generic
        # ``active`` status.
        if current is None:
            current = db.session.scalar(
                db.select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.version_no.desc(), DocumentVersion.created_at.desc())
            )
        item = _document_data(document)
        item["current_version"] = _version_data(current) if current else None
        items.append(item)
    return success({"items": items, "total": result.total, "page": page, "page_size": page_size})


@documents.get("/documents/<uuid:document_id>")
@admin_only
def document_detail(document_id):
    document = _find_document(document_id, include_archived=True)
    return success(_document_data(document, include_versions=True))


@documents.put("/documents/<uuid:document_id>")
@admin_only
def update_document(document_id):
    document = _find_document(document_id, lock=True)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body or set(body) - {"title"}:
        raise ApiError("只支持修改文档标题", 422)
    title = _text(body.get("title"), "文档标题", 255)
    if document.title != title:
        document.title = title
        _record("document.update", document, {"fields": ["title"]})
        db.session.commit()
    return success(_document_data(document))


@documents.post("/documents/presign-upload")
@admin_only
def presign_upload():
    values = _validate_upload_body(request.get_json(silent=True))
    knowledge_base_id, filename, file_size, title, document_id, base_version_id, content_type = values
    _find_knowledge_base(knowledge_base_id)
    document = None
    if document_id:
        document = _find_document(document_id, knowledge_base_id=knowledge_base_id, lock=True)
        latest_version = db.session.scalar(
            db.select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_no.desc())
        )
        expected_base = document.current_version_id or (latest_version.id if latest_version else None)
        if base_version_id != expected_base:
            raise ApiError("文档已产生新版本，请刷新后重新编辑", 409, 40901)
    elif base_version_id:
        raise ApiError("新建文档不能指定基础版本", 422)
    else:
        document = Document(
            id=uuid4(),
            knowledge_base_id=knowledge_base_id,
            title=title,
            status="active",
            created_by=g.user.id,
        )
        db.session.add(document)
        db.session.flush()

    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_no=_next_version(document.id),
        minio_bucket=knowledge_base_bucket(knowledge_base_id),
        minio_object_key=(
            f"knowledge-bases/{knowledge_base_id}/documents/{document.id}/versions/{uuid4()}{PurePath(filename).suffix.lower()}"
        ),
        filename=filename,
        content_type=content_type,
        file_size=file_size,
        status="PENDING_UPLOAD",
        created_by=g.user.id,
    )
    db.session.add(version)
    try:
        upload_url = _api_storage(
            presign_put, version.minio_object_key, bucket=version.minio_bucket
        )
        _record(
            "document.upload.prepare",
            document,
            {"knowledge_base_id": str(knowledge_base_id), "version_id": str(version.id)},
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return success(
        {
            "document": _document_data(document),
            "version": _version_data(version),
            "upload_url": upload_url,
            "upload_method": "PUT",
            "object_key": version.minio_object_key,
            "bucket": version.minio_bucket,
            "required_headers": {"Content-Type": content_type},
            "expires_in": current_app.config["MINIO_URL_SECONDS"],
        }
    ), 201


def _complete_version(version):
    if version.status != "PENDING_UPLOAD":
        if version.status in {"UPLOADED", "PROCESSING", "INDEXED"}:
            task = db.session.scalar(
                db.select(IndexTask)
                .where(IndexTask.document_version_id == version.id)
                .order_by(IndexTask.created_at.desc())
            )
            if task is None and version.status == "UPLOADED":
                task = IndexTask(
                    id=uuid4(), document_version_id=version.id, task_type="INDEX", status="PENDING", attempts=0
                )
                db.session.add(task)
            return task
        raise ApiError("该版本当前不能完成上传", 409, 40901)
    info = _api_storage(stat_object, version.minio_object_key, bucket=version.minio_bucket)
    if int(info.size) != int(version.file_size):
        raise ApiError("MinIO 文件大小与上传信息不一致", 422, 42202)
    content = _api_storage(read_object, version.minio_object_key, bucket=version.minio_bucket, max_size=_max_document_size())
    if PurePath(version.filename).suffix.lower() in TEXT_EXTENSIONS:
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ApiError("文本文件必须使用 UTF-8 编码", 422, 42202) from None
    version.content_hash = hashlib.sha256(content).hexdigest()
    version.status = "UPLOADED"
    version.error_message = None
    task = IndexTask(
        id=uuid4(), document_version_id=version.id, task_type="INDEX", status="PENDING", attempts=0
    )
    db.session.add(task)
    return task


@documents.post("/documents/complete")
@admin_only
def complete_upload():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {"version_id"} or not body.get("version_id"):
        raise ApiError("请提供版本 ID", 422)
    version = _find_version(_uuid(body["version_id"], "版本 ID"), lock=True)
    document = _find_document(version.document_id, lock=False)
    task = _complete_version(version)
    _record("document.upload.complete", document, {"version_id": str(version.id)})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("该版本正在处理，请刷新后重试", 409, 40901) from None
    _schedule_index_task()
    return success({"document": _document_data(document), "version": _version_data(version), "task": _task_data(task)}), 202


@documents.put("/documents/versions/<uuid:version_id>/upload")
@admin_only
def upload_version_fallback(version_id):
    version = _find_version(version_id, lock=True)
    document = _find_document(version.document_id)
    if version.status != "PENDING_UPLOAD":
        raise ApiError("该版本当前不能上传", 409, 40901)
    if request.content_length is None or not 1 <= request.content_length <= _max_document_size():
        raise ApiError("文件大小不正确", 422, 42202)
    content = request.get_data(cache=False, as_text=False)
    if len(content) != request.content_length:
        raise ApiError("文件上传不完整", 422, 42202)
    if PurePath(version.filename).suffix.lower() in TEXT_EXTENSIONS:
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ApiError("文本文件必须使用 UTF-8 编码", 422, 42202) from None
    _api_storage(
        put_object,
        version.minio_object_key,
        BytesIO(content),
        bucket=version.minio_bucket,
        length=len(content),
        content_type=version.content_type or "application/octet-stream",
    )
    version.file_size = len(content)
    task = _complete_version(version)
    _record("document.upload.complete", document, {"version_id": str(version.id), "fallback": True})
    db.session.commit()
    _schedule_index_task()
    return success({"document": _document_data(document), "version": _version_data(version), "task": _task_data(task)}), 202


@documents.get("/documents/<uuid:document_id>/content")
@admin_only
def document_content(document_id):
    document = _find_document(document_id, include_archived=True)
    version_id = request.args.get("version_id") or document.current_version_id
    if not version_id:
        raise ApiError("文档还没有可读取的版本", 404, 40401)
    version = _find_version(_uuid(version_id, "版本 ID"), document_id=document.id)
    if PurePath(version.filename).suffix.lower() not in TEXT_EXTENSIONS:
        raise ApiError("只有 Markdown 或 TXT 文档支持在线文本编辑", 409, 40901)
    content = _api_storage(read_object, version.minio_object_key, bucket=version.minio_bucket, max_size=_max_document_size())
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError("文档内容不是有效的 UTF-8 文本", 422, 42202) from None
    return success({"document": _document_data(document), "version": _version_data(version), "content": text})


@documents.get("/documents/<uuid:document_id>/preview-url")
@admin_only
def document_preview_url(document_id):
    document = _find_document(document_id, include_archived=True)
    version_id = request.args.get("version_id") or document.current_version_id
    if not version_id:
        raise ApiError("文档还没有可预览的版本", 404, 40401)
    version = _find_version(_uuid(version_id, "版本 ID"), document_id=document.id)
    extension = PurePath(version.filename).suffix.lower()
    if extension not in PREVIEWABLE_EXTENSIONS:
        raise ApiError("该文件类型暂不支持在线预览，请下载后查看", 409, 40901)
    url = _api_storage(
        presign_get,
        version.minio_object_key,
        version.filename,
        bucket=version.minio_bucket,
        inline=True,
        content_type=version.content_type,
    )
    return success({"preview_url": url, "expires_in": current_app.config["MINIO_URL_SECONDS"], "version": _version_data(version)})


@documents.get("/documents/<uuid:document_id>/text-preview")
@admin_only
def document_text_preview(document_id):
    document = _find_document(document_id, include_archived=True)
    version_id = request.args.get("version_id") or document.current_version_id
    if not version_id:
        raise ApiError("文档还没有可预览的版本", 404, 40401)
    version = _find_version(_uuid(version_id, "版本 ID"), document_id=document.id)
    if PurePath(version.filename).suffix.lower() not in {".pdf", ".docx"}:
        raise ApiError("该文件类型不支持文本预览", 409, 40901)
    content = _api_storage(read_object, version.minio_object_key, bucket=version.minio_bucket, max_size=_max_document_size())
    try:
        from .indexer import _extract_text

        text = _extract_text(version.filename, content) or ""
    except (RuntimeError, ValueError) as error:
        raise ApiError(str(error), 422, 42202) from error
    return success({"document": _document_data(document), "version": _version_data(version), "content": text})


@documents.get("/documents/<uuid:document_id>/download-url")
@admin_only
def document_download_url(document_id):
    document = _find_document(document_id, include_archived=True)
    version_id = request.args.get("version_id") or document.current_version_id
    if not version_id:
        raise ApiError("文档还没有可下载的版本", 404, 40401)
    version = _find_version(_uuid(version_id, "版本 ID"), document_id=document.id)
    url = _api_storage(presign_get, version.minio_object_key, version.filename, bucket=version.minio_bucket)
    return success({"download_url": url, "expires_in": current_app.config["MINIO_URL_SECONDS"], "version": _version_data(version)})


@documents.post("/documents/<uuid:document_id>/reindex")
@admin_only
def reindex_document(document_id):
    document = _find_document(document_id, lock=True)
    version_id = document.current_version_id or db.session.scalar(
        db.select(DocumentVersion.id)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_no.desc())
    )
    if not version_id:
        raise ApiError("文档没有可处理的版本", 409, 40901)
    version = _find_version(version_id, document_id=document.id, lock=True)
    existing = db.session.scalar(
        db.select(IndexTask)
        .where(IndexTask.document_version_id == version.id, IndexTask.status.in_(("PENDING", "RUNNING")))
        .order_by(IndexTask.created_at.desc())
    )
    if existing:
        _schedule_index_task()
        return success({"task": _task_data(existing), "version": _version_data(version)})
    version.status = "UPLOADED"
    version.error_message = None
    task = IndexTask(id=uuid4(), document_version_id=version.id, task_type="REINDEX", status="PENDING")
    db.session.add(task)
    _record("document.reindex", document, {"version_id": str(version.id)})
    db.session.commit()
    _schedule_index_task()
    return success({"task": _task_data(task), "version": _version_data(version)}), 202


@documents.get("/tasks/<uuid:task_id>")
@admin_only
def task_detail(task_id):
    task = db.session.get(IndexTask, task_id)
    if task is None:
        raise ApiError("索引任务不存在", 404, 40401)
    return success(_task_data(task))


@documents.delete("/documents/<uuid:document_id>")
@admin_only
def archive_document(document_id):
    document = _find_document(document_id, lock=True)
    versions = db.session.scalars(
        db.select(DocumentVersion).where(DocumentVersion.document_id == document.id).with_for_update()
    ).all()
    document.status = "archived"
    document.current_version_id = None
    for version in versions:
        if version.status != "ARCHIVED":
            db.session.add(
                IndexTask(id=uuid4(), document_version_id=version.id, task_type="DELETE", status="PENDING")
            )
    _record("document.archive", document, {"version_count": len(versions)})
    db.session.commit()
    _schedule_index_task()
    return success({"id": str(document.id), "status": document.status}), 202
