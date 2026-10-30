"""Reusable knowledge-base search primitives.

These functions contain query eligibility and score normalization only. HTTP
validation and signed preview URL generation remain in the API adapter.
"""

import math

from ...core.extensions import db
from ...entities import Document, DocumentChunk, DocumentVersion
from ...integrations.ai.embedding_adapter import embed_query as default_embed_query
from ...processors.pdf import readable_source


def available_chunks(knowledge_base_id, model):
    """Return chunks from the current indexed version of active documents."""

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


def cosine(left, right):
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


def search_sources(knowledge_base_id, question, *, top_k=15, embedder=default_embed_query):
    """Search indexed chunks using the supplied embedding adapter."""

    query_vector, model = embedder(question)
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
            score = cosine(chunk.embedding, query_vector)
            if score is not None and math.isfinite(score):
                scored.append((score, chunk, version, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        sources = [
            source_from_row(chunk, version, document, score)
            for score, chunk, version, document in scored[:top_k]
        ]
    return sources, model


__all__ = ["available_chunks", "cosine", "search_sources", "source_from_row"]
