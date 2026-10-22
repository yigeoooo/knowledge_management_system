"""Vector search over the active version of a knowledge base."""

import math
from uuid import UUID

from flask import Blueprint, current_app, request

from .auth import authenticated
from .embedding import EmbeddingError, embed_query
from .extensions import db
from .http import ApiError, success
from .models import Document, DocumentChunk, DocumentVersion, KnowledgeBase
from .storage import StorageError, presign_get

retrieval = Blueprint("retrieval", __name__, url_prefix="/api/v1")


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ApiError("知识库 ID 格式不正确", 422) from None


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


def _source(chunk, version, document, score):
    metadata = chunk.chunk_metadata if isinstance(chunk.chunk_metadata, dict) else {}
    modality = metadata.get("modality", "text")
    source = {
        "document_id": str(document.id),
        "document_title": document.title,
        "version_id": str(version.id),
        "version_no": version.version_no,
        "filename": version.filename,
        "modality": modality,
        "score": round(max(-1.0, min(1.0, score)), 6),
        "heading_path": chunk.heading_path,
        "content": None if modality != "text" else chunk.content,
    }
    if modality != "text":
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
    return source


@retrieval.post("/web/search")
@authenticated
def vector_search():
    body = request.get_json(silent=True)
    allowed = {"knowledge_base_id", "question", "top_k"}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ApiError("请提交知识库 ID 和问题", 422)
    question = body.get("question")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ApiError("问题需为 1–2000 个字符", 422)
    question = question.strip()
    if any(ord(character) < 32 and character not in "\r\n\t" for character in question):
        raise ApiError("问题不能包含控制字符", 422)
    knowledge_base_id = _uuid(body.get("knowledge_base_id"))
    knowledge_base = db.session.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or knowledge_base.status != "active":
        raise ApiError("知识库不存在或已停用", 404, 40401)
    try:
        top_k = int(body.get("top_k", 10))
    except (TypeError, ValueError):
        raise ApiError("召回数量必须是整数", 422) from None
    if not 1 <= top_k <= 20:
        raise ApiError("召回数量需在 1–20 之间", 422)
    try:
        query_vector, model = embed_query(question)
    except EmbeddingError as error:
        raise ApiError(str(error), 503, 50301) from error

    query = (
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
    if db.engine.dialect.name == "postgresql":
        distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
        rows = db.session.execute(query.add_columns(distance).order_by(distance).limit(top_k)).all()
        sources = [_source(chunk, version, document, 1.0 - distance) for chunk, version, document, distance in rows]
    else:
        rows = db.session.execute(query).all()
        scored = []
        for chunk, version, document in rows:
            score = _cosine(chunk.embedding, query_vector)
            if score is not None:
                scored.append((score, chunk, version, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        sources = [_source(chunk, version, document, score) for score, chunk, version, document in scored[:top_k]]
    return success({"knowledge_base_id": str(knowledge_base_id), "model": model, "question": question, "sources": sources})
