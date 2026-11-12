"""Bind evaluation labels to documents in the dataset's knowledge base."""

from uuid import UUID

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import Document, DocumentVersion


def document_reference(reference, base_id):
    result = dict(reference)
    values = result.get("expected_document_ids") or []
    if not values and result.get("expected_documents"):
        raise ApiError("原文档标注尚未绑定文档，请从知识库重新选择预期文档", 422)
    if not isinstance(values, list) or len(values) > 30:
        raise ApiError("最多选择 30 份预期文档", 422)
    try:
        ids = list(dict.fromkeys(UUID(str(value)) for value in values))
    except (ValueError, TypeError):
        raise ApiError("预期文档 ID 格式不正确", 422) from None
    rows = (
        db.session.execute(
            db.select(Document.id, Document.title, DocumentVersion.status)
            .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
            .where(
                Document.id.in_(ids),
                Document.knowledge_base_id == base_id,
                Document.status == "active",
            )
        ).all()
        if ids
        else []
    )
    found = {r.id: r for r in rows}
    if any(id not in found or found[id].status != "INDEXED" for id in ids):
        raise ApiError("所选文档已删除、尚未完成索引或不属于本评测集知识库，请重新选择", 422)
    result["expected_document_ids"] = [str(id) for id in ids]
    # Names are display snapshots only; scoring always uses the stable IDs.
    result["expected_documents"] = [found[id].title for id in ids]
    return result
