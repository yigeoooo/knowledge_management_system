"""Copy bounded conversation ranges into independent evaluation inputs."""

import json

from sqlalchemy import func, or_

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import QAConversation, QALog, Robot, User
from ..conversations.service import COMPLETED


def conversations(base_id, source):
    return db.select(QAConversation).where(
        QAConversation.knowledge_base_id == base_id,
        QAConversation.source_type == source,
        QAConversation.deleted_at.is_(None),
    )


def conversation(base_id, source, cid):
    row = db.session.scalar(conversations(base_id, source).where(QAConversation.id == cid))
    if row is None:
        raise ApiError("会话不存在、已删除或不属于当前知识库和渠道", 404)
    return row


def conversation_data(row):
    return {
        "id": str(row.id),
        "title": row.title,
        "source_type": row.source_type,
        "last_turn_no": row.next_turn_no - 1,
        "last_message_at": row.last_message_at.isoformat(),
    }


def owners(base_id, source, query, page, size):
    model, field = (
        (User, QAConversation.user_id) if source == "WEB" else (Robot, QAConversation.robot_id)
    )
    counts = (
        db.select(field.label("owner_id"), func.count().label("count"))
        .where(
            QAConversation.knowledge_base_id == base_id,
            QAConversation.source_type == source,
            QAConversation.deleted_at.is_(None),
        )
        .group_by(field)
        .subquery()
    )
    name = model.display_name if model is User else model.name
    identity = model.username if model is User else model.serial_no
    statement = db.select(model, counts.c.count).join(counts, counts.c.owner_id == model.id)
    if query:
        statement = statement.where(
            or_(name.icontains(query, autoescape=True), identity.icontains(query, autoescape=True))
        )
    total = db.session.scalar(db.select(func.count()).select_from(statement.subquery()))
    rows = db.session.execute(
        statement.order_by(name, model.id).offset((page - 1) * size).limit(size)
    )
    return {
        "items": [
            {
                "id": str(owner.id),
                "name": (owner.display_name or owner.username)
                if source == "WEB"
                else (owner.name or owner.serial_no),
                "identity": owner.username if source == "WEB" else owner.serial_no,
                "conversation_count": count,
            }
            for owner, count in rows
        ],
        "total": total,
        "page": page,
        "page_size": size,
    }


def history(base_id, source, owner_id, query, page, size):
    field = QAConversation.user_id if source == "WEB" else QAConversation.robot_id
    statement = conversations(base_id, source).where(field == owner_id)
    if query:
        hits = db.select(QALog.conversation_id).where(
            QALog.question.icontains(query, autoescape=True)
        )
        statement = statement.where(
            or_(QAConversation.title.icontains(query, autoescape=True), QAConversation.id.in_(hits))
        )
    result = db.paginate(
        statement.order_by(QAConversation.last_message_at.desc(), QAConversation.id.desc()),
        page=page,
        per_page=size,
        error_out=False,
    )
    return {
        "items": [conversation_data(row) for row in result.items],
        "total": result.total,
        "page": page,
        "page_size": size,
    }


def eligible(row):
    return (
        row.status in COMPLETED and bool(row.question.strip()) and bool((row.answer or "").strip())
    )


def turn_data(row):
    return {
        "id": str(row.id),
        "turn_no": row.turn_no,
        "question": row.question,
        "answer": row.answer,
        "status": row.status,
        "answer_kind": row.answer_kind,
        "importable": eligible(row),
    }


def turns(row, page, size):
    result = db.paginate(
        db.select(QALog).where(QALog.conversation_id == row.id).order_by(QALog.turn_no),
        page=page,
        per_page=size,
        error_out=False,
    )
    return {
        "conversation": conversation_data(row),
        "items": [turn_data(t) for t in result.items],
        "total": result.total,
        "page": page,
        "page_size": size,
    }


def context_copy(row, start, end, task):
    if start > end or end > row.next_turn_no - 1 or end - start + 1 > 30:
        raise ApiError("请选择有效的起止轮次，每次最多导入连续 30 轮", 422)
    if task not in {"answer", "summary"}:
        raise ApiError("仅连续追问和会话摘要支持导入历史", 422)
    logs = db.session.scalars(
        db.select(QALog)
        .where(
            QALog.conversation_id == row.id,
            QALog.turn_no.between(start, end),
        )
        .order_by(QALog.turn_no)
    ).all()
    selected = [log for log in logs if eligible(log)]
    if not selected:
        raise ApiError("所选范围没有已完成且包含回答的问答，请调整范围", 422)
    items = [
        {
            "question": log.question,
            "answer": log.answer,
            "turn_no": log.turn_no,
            "status": log.status,
            "answer_kind": log.answer_kind,
            "source_log_id": str(log.id),
            "source_conversation_id": str(row.id),
        }
        for log in selected
    ]
    # The latest memory summary may cover later turns. Never import it into an earlier range.
    context = {"summary": "", "turns": items}
    if len(json.dumps(context, ensure_ascii=False)) > 20000:
        raise ApiError("所选历史超过测试题的 20000 字限制，请缩小轮次范围", 422)
    if task == "summary" and len(json.dumps(items, ensure_ascii=False).encode()) > 18000:
        raise ApiError("所选历史超过摘要测试的 18000 字节限制，请缩小轮次范围", 422)
    return {
        "context": context,
        "conversation": conversation_data(row),
        "skipped_count": len(logs) - len(selected),
        "start_turn_no": start,
        "end_turn_no": end,
    }
