"""All callers share ownership, ordering, binding and idempotency rules."""

import re
from uuid import UUID, uuid4

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import AuditLog, KnowledgeBase, QAConversation, QALog, Robot, User, now
from ...security.permissions import accessible_pages

INFLIGHT = ("PENDING", "PROCESSING")
COMPLETED = ("SUCCESS", "PARTIAL", "NO_EVIDENCE", "SOURCES_ONLY")


def uuid_value(value, label="ID"):
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise ApiError(f"{label}格式不正确", 422) from None


def request_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value):
        raise ApiError("请提供有效的 request_id，网络重试应复用原编号", 422)
    return value


def active_base(base_id):
    base = db.session.get(KnowledgeBase, base_id, populate_existing=True)
    if not base or base.status != "active":
        raise ApiError("知识库不存在或已停用", 409, 40910)
    return base


def lock_robot(robot_id, *, skip_locked=False):
    return db.session.scalar(
        db.select(Robot)
        .where(Robot.id == robot_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )


def robot_ready(robot):
    if not robot or robot.status != "active":
        raise ApiError("机器人未注册或已停用", 403, 43001)
    if not robot.knowledge_base_id:
        raise ApiError("机器人尚未绑定知识库，请联系管理员", 409, 40911)
    active_base(robot.knowledge_base_id)


def get_conversation(cid, *, user_id=None, robot_id=None, admin=False, lock=False):
    query = db.select(QAConversation).where(QAConversation.id == uuid_value(cid, "会话 ID"))
    if not admin:
        query = query.where(QAConversation.deleted_at.is_(None))
        if robot_id is not None:
            query = query.where(
                QAConversation.robot_id == robot_id, QAConversation.source_type == "ROBOT"
            )
        else:
            query = query.where(
                QAConversation.user_id == user_id, QAConversation.source_type == "WEB"
            )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    conversation = db.session.scalar(query)
    if conversation is None:
        raise ApiError("会话不存在或已删除", 404, 40401)
    return conversation


def writable(conversation, robot=None):
    if conversation.deleted_at:
        raise ApiError("会话已删除", 404, 40401)
    if robot is not None:
        robot_ready(robot)
        if (
            conversation.robot_id != robot.id
            or conversation.robot_binding_version != robot.binding_version
            or conversation.knowledge_base_id != robot.knowledge_base_id
        ):
            raise ApiError("机器人知识库绑定已变更，请开启新对话", 409, 40912)
    if conversation.closed_at:
        raise ApiError("此会话已关闭，请开启新对话", 409, 40912)
    active_base(conversation.knowledge_base_id)


def user_ready(user_id):
    user = db.session.get(User, user_id, populate_existing=True)
    if not user or user.status != "active" or user.role.status != "active":
        raise ApiError("用户或角色已停用", 403)
    if user.role.code != "super_admin" and not any(
        page.route_path == "/qa" and page.page_type != "button" for page in accessible_pages(user)
    ):
        raise ApiError("用户已失去问答权限", 403)


def conversation_data(c):
    base = db.session.get(KnowledgeBase, c.knowledge_base_id)
    owner = db.session.get(User, c.user_id) if c.user_id else db.session.get(Robot, c.robot_id)
    return {
        "id": str(c.id),
        "title": c.title,
        "source_type": c.source_type,
        "user_id": str(c.user_id) if c.user_id else None,
        "robot_id": str(c.robot_id) if c.robot_id else None,
        "owner_name": (
            getattr(owner, "display_name", None)
            or getattr(owner, "name", None)
            or getattr(owner, "serial_no", None)
            or "未知用户"
        ),
        "knowledge_base_id": str(c.knowledge_base_id),
        "knowledge_base_name": base.name if base else "知识库已不存在",
        "knowledge_base_status": base.status if base else "archived",
        "last_turn_no": c.next_turn_no - 1,
        "turn_count": c.next_turn_no - 1,
        "created_at": c.created_at.isoformat(),
        "last_message_at": c.last_message_at.isoformat(),
        "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
        "closed_at": c.closed_at.isoformat() if c.closed_at else None,
        "closed_reason": c.closed_reason,
    }


def turn_data(log, *, robot=False):
    from ...api.retrieval.controller import with_preview_urls
    from ...processors.answer_text import robot_answer_text
    from ...processors.pdf import readable_answer
    from ..qa.grounding_service import ROBOT_FORMAT_NOTICE, ROBOT_NO_EVIDENCE

    sources = log.sources or []
    answer = readable_answer(log.answer, sources) if log.answer else None
    if robot and answer:
        if log.status == "NO_EVIDENCE":
            answer = ROBOT_NO_EVIDENCE
        elif log.status == "SOURCES_ONLY":
            answer = ROBOT_FORMAT_NOTICE
        else:
            answer = robot_answer_text(answer, sources)
    return {
        "id": str(log.id),
        "turn_id": str(log.id),
        "conversation_id": str(log.conversation_id),
        "turn_no": log.turn_no,
        "request_id": log.request_id,
        "question": log.question,
        "answer": answer,
        "status": log.status,
        "answer_kind": log.answer_kind,
        "answer_status": {
            "SUCCESS": "answered",
            "PARTIAL": "partial",
            "SOURCES_ONLY": "sources_only",
        }.get(log.status, "insufficient_evidence"),
        "sources": [] if robot else with_preview_urls(sources),
        "model_name": log.model_name,
        "latency_ms": log.latency_ms,
        "retrieval_count": log.retrieval_count,
        "error_message": log.error_message,
        "created_at": log.created_at.isoformat(),
        "poll_after_ms": 1000,
        "context_notice": (log.context_snapshot or {}).get("notice"),
    }


def submit(
    *,
    question,
    request_id,
    user_id=None,
    robot_id=None,
    conversation_id=None,
    knowledge_base_id=None,
    expected_last_turn_no=None,
    anchor=None,
):
    """Commit receipt before waking a worker. Never invoke a model in this transaction."""
    from ...api.retrieval.controller import validate_question

    question = validate_question(question)
    request_id = request_key(request_id)
    if expected_last_turn_no is not None and (
        type(expected_last_turn_no) is not int or expected_last_turn_no < 0
    ):
        raise ApiError("expected_last_turn_no 必须为非负整数", 422)
    robot = lock_robot(robot_id) if robot_id else None
    if robot_id:
        robot_ready(robot)
    else:
        # Serializes first-turn retries even before a conversation row exists.
        db.session.scalar(db.select(User).where(User.id == user_id).with_for_update())
        user_ready(user_id)
    existing = db.session.scalar(db.select(QALog).where(QALog.request_id == request_id))
    if existing:
        same = (
            existing.user_id == user_id
            and existing.robot_id == robot_id
            and existing.question == question
        )
        if conversation_id:
            same = same and existing.conversation_id == uuid_value(conversation_id)
        elif existing.conversation_id:
            first = db.session.get(QAConversation, existing.conversation_id)
            same = same and first.creation_request_id == request_id
        else:
            same = False
        if knowledge_base_id:
            same = same and existing.knowledge_base_id == uuid_value(knowledge_base_id)
        if not same:
            raise ApiError("请求编号已被其他问题使用", 409, 40901)
        c = get_conversation(
            existing.conversation_id, user_id=user_id, robot_id=robot_id, lock=True
        )
        writable(c, robot)
        db.session.commit()
        return c, existing
    if conversation_id:
        c = get_conversation(conversation_id, user_id=user_id, robot_id=robot_id, lock=True)
        writable(c, robot)
    else:
        base_id = robot.knowledge_base_id if robot else uuid_value(knowledge_base_id, "知识库 ID")
        active_base(base_id)
        c = QAConversation(
            id=uuid4(),
            source_type="ROBOT" if robot else "WEB",
            user_id=user_id,
            robot_id=robot_id,
            knowledge_base_id=base_id,
            robot_binding_version=robot.binding_version if robot else None,
            title=question[:80],
            creation_request_id=request_id,
            next_turn_no=1,
        )
        db.session.add(c)
        db.session.flush()
    if expected_last_turn_no is not None and c.next_turn_no - 1 != expected_last_turn_no:
        raise ApiError("会话已有新消息，请刷新后发送", 409, 40913)
    busy = db.session.scalar(
        db.select(QALog.id).where(QALog.conversation_id == c.id, QALog.status.in_(INFLIGHT))
    )
    if busy:
        raise ApiError("本会话正在回答，请等待当前问题完成", 409, 40902)
    log = QALog(
        id=uuid4(),
        request_id=request_id,
        source_type=c.source_type,
        user_id=c.user_id,
        robot_id=c.robot_id,
        knowledge_base_id=c.knowledge_base_id,
        conversation_id=c.id,
        turn_no=c.next_turn_no,
        question=question,
        status="PENDING",
        sources=[],
        suggestion_anchor=anchor,
    )
    c.next_turn_no += 1
    c.last_message_at = now()
    if robot:
        robot.last_request_at = now()
    db.session.add(log)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("请求与正在提交的问题冲突，请复用请求编号重试", 409, 40902) from None
    return c, log


def cancel_pending(c, reason):
    db.session.execute(
        db.update(QALog)
        .where(QALog.conversation_id == c.id, QALog.status.in_(INFLIGHT))
        .values(status="CANCELLED", error_message=reason, lease_token=None, lease_expires_at=None)
    )


def delete_conversation(cid, *, user_id=None, robot_id=None):
    if robot_id:
        lock_robot(robot_id)
    # Allow repeated deletion by its owner without exposing someone else's record.
    c = get_conversation(cid, admin=True, lock=True)
    if c.user_id != user_id or c.robot_id != robot_id:
        raise ApiError("会话不存在", 404)
    if not c.deleted_at:
        c.deleted_at = now()
        cancel_pending(c, "会话已删除")
        db.session.add(
            AuditLog(
                user_id=user_id,
                action="conversation.delete",
                resource_type="conversation",
                resource_id=c.id,
                detail={"robot_id": str(robot_id) if robot_id else None},
            )
        )
        db.session.commit()
    return {"id": str(c.id), "deleted": True}


def retry_turn(cid, tid, *, user_id=None, robot_id=None):
    robot = lock_robot(robot_id) if robot_id else None
    c = get_conversation(cid, user_id=user_id, robot_id=robot_id, lock=True)
    writable(c, robot)
    log = db.session.scalar(
        db.select(QALog)
        .where(QALog.id == uuid_value(tid), QALog.conversation_id == c.id)
        .with_for_update()
    )
    if not log:
        raise ApiError("问答不存在", 404)
    if log.turn_no != c.next_turn_no - 1:
        raise ApiError("只能重试最后一轮，请重新发送问题", 409)
    if log.status in INFLIGHT:
        return log
    if log.status != "FAILED":
        raise ApiError("当前问答不可重试", 409)
    log.status, log.error_message = "PENDING", None
    log.lease_token, log.lease_expires_at = None, None
    log.attempts = 0
    db.session.commit()
    return log


def rebind_robot(robot, base_id, expected_version):
    base_id = uuid_value(base_id, "知识库 ID")
    active_base(base_id)
    if base_id == robot.knowledge_base_id:
        return
    if expected_version is not None and (
        type(expected_version) is not int or expected_version != robot.binding_version
    ):
        raise ApiError("机器人绑定已被其他管理员修改，请刷新", 409, 40914)
    robot.knowledge_base_id = base_id
    robot.binding_version += 1
    for c in db.session.scalars(
        db.select(QAConversation)
        .where(QAConversation.robot_id == robot.id, QAConversation.closed_at.is_(None))
        .with_for_update()
    ):
        c.closed_at, c.closed_reason = now(), "knowledge_base_changed"
        cancel_pending(c, "机器人知识库已换绑，请开启新对话")


def wake_worker():
    if current_app.config.get("QA_WORKER_AUTOSTART") and not current_app.testing:
        from ...workers.qa_worker import schedule_worker

        schedule_worker(current_app._get_current_object())
