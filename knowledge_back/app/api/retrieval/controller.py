"""Vector search over the active version of a knowledge base."""

from uuid import UUID

from flask import Blueprint, current_app, request

from ...api.auth.controller import page_required
from ...application.qa.search_service import (
    search_sources as _search_sources,
)
from ...core.extensions import db
from ...core.http import ApiError, success
from ...entities import DocumentVersion, KnowledgeBase
from ...integrations.ai.embedding_adapter import EmbeddingError, embed_query
from ...integrations.storage.minio_adapter import StorageError, presign_get, read_object
from ...processors.pdf import readable_source

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


def with_preview_urls(sources):
    """Generate fresh media links at response time; never persist signed URLs in logs."""
    result = []
    word_versions = {}
    for original in sources:
        source = readable_source(original)
        result.append(source)
        if str(source.get("filename", "")).lower().endswith(".docx") and source.get("content"):
            # Derived for display only. Grounding and saved evidence keep the
            # original text; historical views use the original version UUID.
            source.pop("content_html", None)
            try:
                version_id = UUID(str(source.get("version_id")))
                version = db.session.get(DocumentVersion, version_id)
                if (version is None or not version.filename.lower().endswith(".docx")
                        or str(version.document_id) != source.get("document_id")):
                    continue
                from ...docx_preview import citation_html, docx_html

                if version_id not in word_versions:
                    word_versions[version_id] = None
                    payload = read_object(version.minio_object_key, bucket=version.minio_bucket,
                                          max_size=current_app.config["MAX_DOCUMENT_SIZE"])
                    word_versions[version_id] = docx_html(payload)
                rendered = word_versions[version_id]
                if rendered and (fragment := citation_html(rendered, source["content"])):
                    source["content_html"] = fragment
            except (StorageError, ApiError, ValueError, TypeError, KeyError):
                # Storage loss must not make a previously saved answer unreadable.
                pass
        if source.get("modality") not in {"image", "video"}:
            continue
        try:
            version = db.session.get(DocumentVersion, UUID(str(source.get("version_id"))))
        except (ValueError, TypeError):
            version = None
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
    # Keep the adapter at the HTTP seam so existing test and deployment
    # overrides can replace the embedding provider without touching services.
    return _search_sources(knowledge_base_id, question, top_k=top_k, embedder=embed_query)


@retrieval.post("/web/search")
@page_required("/qa")
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
