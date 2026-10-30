"""Resolve resource operators in a batch from creation and committed change audits."""

from sqlalchemy import func

from ...core.extensions import db
from ...entities import AuditLog, User

CHANGE_ACTIONS = {
    "knowledge_base": ("knowledge_base.create", "knowledge_base.update", "knowledge_base.archive"),
    "document": (
        "document.create",
        "document.update",
        "document.upload.complete",
        "document.word.edit",
        "document.excel.edit",
        "document.archive",
    ),
}


def operator_names(records, resource_type):
    """Two queries per page, independent of the number of records.

    Upload preparation, downloads and worker/reindex activity are not content
    edits. Resolve display names live so user renames also apply to old records.
    """
    if not records:
        return {}
    ids = [record.id for record in records]
    ranked = (
        db.select(
            AuditLog.resource_id,
            AuditLog.user_id,
            func.row_number()
            .over(
                partition_by=AuditLog.resource_id,
                order_by=(AuditLog.created_at.desc(), AuditLog.id.desc()),
            )
            .label("rank"),
        )
        .where(
            AuditLog.resource_type == resource_type,
            AuditLog.resource_id.in_(ids),
            AuditLog.action.in_(CHANGE_ACTIONS[resource_type]),
        )
        .subquery()
    )
    last_editors = dict(
        db.session.execute(
            db.select(ranked.c.resource_id, ranked.c.user_id).where(ranked.c.rank == 1)
        ).all()
    )
    user_ids = {record.created_by for record in records} | set(last_editors.values())
    user_ids.discard(None)
    names = (
        dict(
            db.session.execute(
                db.select(User.id, User.display_name).where(User.id.in_(user_ids))
            ).all()
        )
        if user_ids
        else {}
    )
    return {
        record.id: {
            "created_by_name": names.get(record.created_by) or "—",
            "updated_by_name": names.get(last_editors.get(record.id, record.created_by)) or "—",
        }
        for record in records
    }
