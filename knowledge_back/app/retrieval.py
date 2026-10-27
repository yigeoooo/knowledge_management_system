"""Vector search over the active version of a knowledge base."""

import math
from uuid import UUID

from flask import Blueprint, current_app, request

from .auth import authenticated
from .embedding import EmbeddingError, embed_query
from .extensions import db
from .http import ApiError, success
from .models import Document, DocumentChunk, DocumentVersion, KnowledgeBase
from .pdf_text import readable_source
from .storage import StorageError, presign_get

retrieval = Blueprint("retrieval", __name__, url_prefix="/api/v1")


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ApiError("知识库 ID 格式不正确", 422) from None


def require_knowledge_base(value):
    knowledge_base = db.session.get(KnowledgeBase, _uuid(value), populate_existing=True)
    if knowledge_base is None or knowledge_base.status != "active":
        raise ApiError("知识库不存在或已停用", 404, 40401)
    return knowledge_base


def validate_question(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
        raise ApiError("问题需为 1–2000 个字符", 422)
    value = value.strip()
    if any((ord(c) < 32 and c not in "\r\n\t") or ord(c) == 127 for c in value):
        raise ApiError("问题不能包含控制字符", 422)
    return value


def available_chunks(knowledge_base_id, model):
    """One eligibility rule shared by search, recommendations and answer validation."""
    return (
        db.select(DocumentChunk, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.status == "active",
            Document.current_version_id == DocumentVersion.id,
            DocumentVersion.status == "INDEXED",
            DocumentVersion.embedding_model == model,
        )
    )


def _cosine(left, right):
    if not isinstance(left, list) or len(left) != len(right):
        return None
    try:
        numerator = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
        right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    except (TypeError, ValueError):
        return None
    if not left_norm or not right_norm:
        return None
    return numerator / (left_norm * right_norm)


def source_from_row(chunk, version, document, score=None):
    metadata = chunk.chunk_metadata if isinstance(chunk.chunk_metadata, dict) else {}
    modality = metadata.get("modality", "text")
    source = {
        "chunk_id": str(chunk.id),
        "document_id": str(document.id),
        "document_title": document.title,
        "version_id": str(version.id),
        "version_no": version.version_no,
        "filename": version.filename,
        "modality": modality,
        "score": round(max(-1.0, min(1.0, score)), 6) if score is not None else None,
        "heading_path": chunk.heading_path,
        "content": None if modality != "text" else chunk.content,
    }
    return readable_source(source)


def with_preview_urls(sources):
    """Generate fresh media links at response time; never persist signed URLs in logs."""
    result = []
    for original in sources:
        source = readable_source(original)
        result.append(source)
        if source.get("modality") not in {"image", "video"}:
            continue
        version = db.session.get(DocumentVersion, UUID(source["version_id"]))
        if version is None:
            source["preview_url"] = None
            continue
        try:
            source["preview_url"] = presign_get(
                version.minio_object_key,
                version.filename,
                bucket=version.minio_bucket,
                inline=True,
                content_type=version.content_type,
            )
            source["preview_expires_in"] = current_app.config["MINIO_URL_SECONDS"]
        except StorageError:
            # A search hit is still useful when object storage is temporarily
            # unavailable; the document preview endpoint can be retried.
            source["preview_url"] = None
    return result


def search_sources(knowledge_base_id, question, *, top_k=15):
    query_vector, model = embed_query(question)
    query = available_chunks(knowledge_base_id, model)
    if db.engine.dialect.name == "postgresql":
        distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
        rows = db.session.execute(query.add_columns(distance).order_by(distance).limit(top_k)).all()
        sources = [
            source_from_row(chunk, version, document, 1.0 - distance)
            for chunk, version, document, distance in rows
            if distance is not None and math.isfinite(distance)
        ]
    else:
        scored = []
        for chunk, version, document in db.session.execute(query):
            score = _cosine(chunk.embedding, query_vector)
            if score is not None and math.isfinite(score):
                scored.append((score, chunk, version, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        sources = [
            source_from_row(chunk, version, document, score)
            for score, chunk, version, document in scored[:top_k]
        ]
    return sources, model


@retrieval.post("/web/search")
@authenticated
def vector_search():
    body = request.get_json(silent=True)
    allowed = {"knowledge_base_id", "question", "top_k"}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ApiError("请提交知识库 ID 和问题", 422)
    question = validate_question(body.get("question"))
    knowledge_base_id = require_knowledge_base(body.get("knowledge_base_id")).id
    try:
        top_k = int(body.get("top_k", 10))
    except (TypeError, ValueError):
        raise ApiError("召回数量必须是整数", 422) from None
    if not 1 <= top_k <= 20:
        raise ApiError("召回数量需在 1–20 之间", 422)
    try:
        sources, model = search_sources(knowledge_base_id, question, top_k=top_k)
    except EmbeddingError as error:
        raise ApiError(str(error), 503, 50301) from error

    return success(
        {
            "knowledge_base_id": str(knowledge_base_id),
            "model": model,
            "question": question,
            "sources": with_preview_urls(sources),
        }
    )
