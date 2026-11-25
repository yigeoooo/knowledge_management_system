"""PostgreSQL-backed document indexing worker."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePath
from threading import Lock

from flask import current_app
from langchain_core.runnables import RunnableLambda

from ..application.documents.index_profile import configured_profile, profile_hash
from ..core.extensions import db
from ..entities import Document, DocumentChunk, DocumentVersion, IndexTask, now
from ..integrations.ai.embedding_adapter import EmbeddingError, embed_contents, embed_texts
from ..integrations.ai.langchain_adapters import DashScopeEmbeddings
from ..integrations.ai.langsmith_config import tracing_scope
from ..integrations.storage.minio_adapter import (
    StorageError,
    delete_object,
    presign_get,
    read_object,
)
from ..processors.pdf import normalize_pdf_text
from ..processors.rag_documents import KnowledgeTextSplitter, excel_documents

TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
MEDIA_MODALITIES = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".mp4": "video",
    ".webm": "video",
    ".mov": "video",
    ".avi": "video",
}

_background_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-indexer")
_background_lock = Lock()
_background_running = False


def schedule_worker(app) -> None:
    """Drain pending tasks in the web process after an upload or reindex.

    The database task queue remains the source of truth, so a separate worker
    process can still be used in production.  The single in-process runner is
    deliberately guarded to avoid duplicate embedding calls when several
    requests finish at once.
    """

    global _background_running
    with _background_lock:
        if _background_running:
            return
        _background_running = True
    _background_executor.submit(_drain_scheduled_tasks, app)


def _drain_scheduled_tasks(app) -> None:
    global _background_running
    try:
        while process_one(app):
            pass
    finally:
        with _background_lock:
            _background_running = False


def _extract_text(filename: str, content: bytes) -> str | None:
    extension = PurePath(filename).suffix.lower()
    if extension in TEXT_EXTENSIONS:
        return content.decode("utf-8-sig")
    if extension == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(__import__("io").BytesIO(content))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            return normalize_pdf_text(text).strip()
        except Exception as error:
            raise RuntimeError("PDF 文本提取失败，请确认文件没有加密") from error
    if extension == ".docx":
        try:
            from docx import Document as WordDocument

            document = WordDocument(__import__("io").BytesIO(content))
            from docx.table import Table

            paragraphs = []
            for block in document.iter_inner_content():
                if isinstance(block, Table):
                    paragraphs.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
                elif block.text.strip():
                    value = block.text.strip()
                    import re
                    style = block.style.name if block.style else ""
                    match = re.search(r"(?:Heading|标题)\s*([1-6])", style, re.IGNORECASE)
                    if match:
                        value = "#" * int(match.group(1)) + " " + value
                    elif len(value) < 80 and re.match(r"^[一二三四五六七八九十]+、[^。；！？]+[：:]?$", value):
                        value = "## " + value
                    paragraphs.append(value)
            return "\n\n".join(paragraphs).strip()
        except Exception as error:
            raise RuntimeError("Word 文本提取失败，请确认文件格式有效") from error
    if extension == ".doc":
        return None
    if extension in {".xls", ".xlsx"}:
        try:
            from ..processors.excel.workbook import parse_workbook, workbook_text

            return workbook_text(parse_workbook(filename, content)).strip()
        except Exception as error:
            raise RuntimeError("Excel 文本提取失败，请确认文件格式有效") from error
    if extension in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".mov", ".avi"}:
        return None
    raise RuntimeError("不支持的文档类型")


def _media_modality(filename: str) -> str | None:
    return MEDIA_MODALITIES.get(PurePath(filename).suffix.lower())


def _claim_task():
    task = db.session.scalar(
        db.select(IndexTask)
        .where(IndexTask.status == "PENDING")
        .order_by(IndexTask.created_at, IndexTask.id)
        .with_for_update(skip_locked=True)
    )
    if task is None:
        db.session.rollback()
        return None
    task.status = "RUNNING"
    task.attempts += 1
    task.started_at = now()
    task.error_message = None
    version = db.session.get(DocumentVersion, task.document_version_id)
    if version and task.task_type != "DELETE":
        version.status = "PROCESSING"
        version.error_message = None
    db.session.commit()
    return task.id


def _finish_failure(task_id, error):
    task = db.session.get(IndexTask, task_id)
    if task is None:
        return
    task.status = "FAILED"
    task.error_message = str(error)[:2000]
    task.finished_at = now()
    version = db.session.get(DocumentVersion, task.document_version_id)
    if version and task.task_type != "DELETE":
        version.status = "FAILED"
        version.error_message = task.error_message
    db.session.commit()


def _process_delete(task):
    version = db.session.get(DocumentVersion, task.document_version_id)
    if version is None:
        return
    db.session.execute(db.delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
    delete_object(version.minio_object_key, bucket=version.minio_bucket)
    version.status = "ARCHIVED"
    version.chunk_count = 0


def _process_index(task):
    version = db.session.get(DocumentVersion, task.document_version_id)
    if version is None:
        raise RuntimeError("文档版本不存在")
    content = read_object(version.minio_object_key, bucket=version.minio_bucket, max_size=current_app.config["MAX_DOCUMENT_SIZE"])
    text = _extract_text(version.filename, content)
    if text is None:
        modality = _media_modality(version.filename)
        if modality:
            # DashScope accepts a publicly reachable URL for image/video
            # contents.  A short-lived MinIO URL keeps the bucket private while
            # allowing the provider to fetch the object during this task.
            media_url = presign_get(
                version.minio_object_key,
                version.filename,
                bucket=version.minio_bucket,
                inline=True,
                content_type=version.content_type,
            )
            version.status = "EMBEDDING"
            db.session.commit()
            vectors, model = embed_contents([{modality: media_url}])
            if len(vectors) != 1:
                raise EmbeddingError("多模态 Embedding 服务没有返回媒体向量")
            db.session.execute(db.delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
            db.session.add(
                DocumentChunk(
                    id=__import__("uuid").uuid4(),
                    document_version_id=version.id,
                    chunk_index=0,
                    content=f"{modality} 文件：{version.filename}",
                    heading_path=None,
                    token_count=0,
                    embedding=vectors[0],
                    chunk_metadata={
                        "modality": modality,
                        "filename": version.filename,
                        "minio_object_key": version.minio_object_key,
                    },
                )
            )
            version.chunk_count = 1
            version.embedding_model = model
            version.status = "INDEXED"
            version.error_message = None
        else:
            # DOC files are retained as managed resources because reliable
            # extraction is unavailable in the current worker.
            version.chunk_count = 0
            version.embedding_model = None
            version.status = "INDEXED"
            version.error_message = "该文件类型不包含可直接提取的文本，已完成文件管理"
    else:
        text = text.strip()
        if not text:
            raise RuntimeError("文档中没有可索引的文本")
        extension = PurePath(version.filename).suffix.lower()
        if extension in {".xlsx", ".xls"}:
            from ..processors.excel.workbook import parse_workbook
            chunks = excel_documents(parse_workbook(version.filename, content), version_id=version.id)
        else:
            chunks = KnowledgeTextSplitter().create_documents([text], [{"version_id": str(version.id)}])
        version.status = "EMBEDDING"
        db.session.commit()
        embeddings = DashScopeEmbeddings(documents_fn=embed_texts)
        with tracing_scope():
            vectors = RunnableLambda(embeddings.embed_documents).invoke(
                [chunk.page_content for chunk in chunks], config={"run_name": "index.embed_documents"})
        model = embeddings.model
        if len(vectors) != len(chunks):
            raise EmbeddingError("Embedding 服务返回的向量数量与文档切片数量不一致")
        db.session.execute(db.delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            db.session.add(
                DocumentChunk(
                    id=__import__("uuid").uuid4(),
                    document_version_id=version.id,
                    chunk_index=index,
                    content=chunk.page_content,
                    heading_path=chunk.metadata.get("heading_path"),
                    token_count=max(1, len(chunk.page_content)),
                    embedding=vector,
                    chunk_metadata={**chunk.metadata, "previous_index": index - 1 if index else None,
                                    "next_index": index + 1 if index + 1 < len(chunks) else None},
                )
            )
        version.chunk_count = len(chunks)
        version.embedding_model = model
        version.status = "INDEXED"
        version.error_message = None
    if version.embedding_model:
        profile = configured_profile(version.embedding_model, len(vectors[0]) if vectors else None)
        extension = PurePath(version.filename).suffix.lower()
        if _media_modality(version.filename):
            profile.update(chunk_strategy="media-single-object", chunk_size=None, chunk_overlap=0)
        elif extension in {".xlsx", ".xls"}:
            profile.update(chunk_strategy="excel-row-with-header", chunk_size=None, chunk_overlap=0)
        profile["source_extension"] = extension
        version.index_profile, version.index_config_hash = profile, profile_hash(profile)
    document = db.session.get(Document, version.document_id)
    if document and document.status == "active":
        current = db.session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
        if current is None or version.version_no >= current.version_no:
            document.current_version_id = version.id


def process_one(app) -> bool:
    with app.app_context():
        task_id = _claim_task()
        if task_id is None:
            return False
        app.logger.info("index task started task=%s", task_id)
        try:
            task = db.session.get(IndexTask, task_id)
            if task.task_type == "DELETE":
                _process_delete(task)
            else:
                _process_index(task)
            task.status = "SUCCESS"
            task.finished_at = now()
            task.error_message = None
            db.session.commit()
            app.logger.info("index task completed task=%s", task_id)
        except (EmbeddingError, StorageError, UnicodeDecodeError, RuntimeError, ValueError) as error:
            app.logger.exception("index task failed task=%s type=%s", task_id, type(error).__name__)
            db.session.rollback()
            _finish_failure(task_id, error)
        except Exception:
            current_app.logger.exception("index task failed task=%s", task_id)
            db.session.rollback()
            _finish_failure(task_id, "索引任务执行失败")
        return True


def run_worker(app, *, once=False, interval=2):
    import time

    processed = 0
    while True:
        if not process_one(app):
            if once:
                return processed
            time.sleep(interval)
            continue
        processed += 1
        if once and processed >= app.config.get("INDEX_WORKER_BATCH_SIZE", 1):
            return processed
