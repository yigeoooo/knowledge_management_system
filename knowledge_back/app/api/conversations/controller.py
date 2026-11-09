"""HTTP adapters for user/robot conversations and owner-first audit browsing."""

from datetime import datetime
from io import BytesIO

from flask import Blueprint, current_app, g, request, send_file
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, or_

from ...application.conversations import service as svc
from ...application.conversations.robot_answers import wait_for_answer
from ...core.extensions import db, limiter
from ...core.http import ApiError, success
from ...entities import QAConversation, QALog, Robot, User
from ..auth.controller import page_required

conversations = Blueprint("conversations", __name__, url_prefix="/api/v1")


def body(allowed):
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ApiError("请求参数不正确", 422)
    return value


def number(name, default, maximum):
    value = request.args.get(name)
    try:
        result = int(value) if value is not None else default
    except ValueError:
        raise ApiError("分页参数不正确", 422) from None
    if not 1 <= result <= maximum:
        raise ApiError("分页参数超出范围", 422)
    return result


def robot_identity():
    serial = request.headers.get("X-Robot-Serial")
    if request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            serial = data.get("serial_no", serial)
    if not isinstance(serial, str) or not 1 <= len(serial.strip()) <= 100:
        raise ApiError("请提供机器人序列号", 422)
    robot = db.session.scalar(db.select(Robot).where(Robot.serial_no == serial.strip()))
    if not robot or robot.status != "active":
        raise ApiError("机器人未注册或已停用", 403, 43001)
    g.robot_id = robot.id
    return robot


def submitted(c, log, *, robot=False):
    response = {"conversation": svc.conversation_data(c), **svc.turn_data(log, robot=robot)}
    svc.wake_worker()
    return success(response), 202 if log.status in svc.INFLIGHT else 200


@conversations.post("/web/conversations")
@page_required("/qa")
@limiter.limit("20 per minute", key_func=lambda: str(g.user.id))
def create_web():
    data = body({"question", "request_id", "knowledge_base_id", "suggestion_token"})
    anchor = None
    if data.get("suggestion_token"):
        from ..qa.controller import _suggestion_anchor
        from ..retrieval.controller import validate_question

        anchor = _suggestion_anchor(
            data["suggestion_token"],
            g.user.id,
            svc.uuid_value(data.get("knowledge_base_id")),
            validate_question(data.get("question")),
        )
    c, log = svc.submit(
        user_id=g.user.id,
        question=data.get("question"),
        request_id=data.get("request_id"),
        knowledge_base_id=data.get("knowledge_base_id"),
        anchor=anchor,
    )
    return submitted(c, log)


@conversations.post("/web/conversations/<uuid:cid>/turns")
@page_required("/qa")
@limiter.limit("20 per minute", key_func=lambda: str(g.user.id))
def web_question(cid):
    data = body({"question", "request_id", "expected_last_turn_no"})
    c, log = svc.submit(
        user_id=g.user.id,
        conversation_id=cid,
        question=data.get("question"),
        request_id=data.get("request_id"),
        expected_last_turn_no=data.get("expected_last_turn_no"),
    )
    return submitted(c, log)


@conversations.post("/robot/query")
@limiter.limit("60 per minute")
def robot_first():
    data = body({"serial_no", "question", "request_id"})
    robot = robot_identity()
    with limiter.limit("20 per minute", key_func=lambda: str(g.robot_id)):
        c, log = svc.submit(
            robot_id=robot.id, question=data.get("question"), request_id=data.get("request_id")
        )
        return success(wait_for_answer(c.id, log.id, robot.id))


@conversations.post("/robot/conversations/query")
@limiter.limit("60 per minute")
def robot_continue():
    data = body({"serial_no", "question", "request_id", "conversation_id", "expected_last_turn_no"})
    cid = svc.uuid_value(data.get("conversation_id"), "会话 ID")
    robot = robot_identity()
    with limiter.limit("20 per minute", key_func=lambda: str(g.robot_id)):
        c, log = svc.submit(
            robot_id=robot.id,
            conversation_id=cid,
            question=data.get("question"),
            request_id=data.get("request_id"),
            expected_last_turn_no=data.get("expected_last_turn_no"),
        )
        return success(wait_for_answer(c.id, log.id, robot.id))


def history(query):
    size = number("page_size", 30, 100)
    signer = URLSafeSerializer(current_app.config["JWT_SECRET_KEY"], salt="conversation-cursor")
    cursor = request.args.get("cursor")
    if cursor:
        try:
            time, cid = signer.loads(cursor)
            time, cid = datetime.fromisoformat(time), svc.uuid_value(cid)
        except (BadSignature, ValueError, TypeError):
            raise ApiError("历史游标不正确", 422) from None
        query = query.where(
            or_(
                QAConversation.last_message_at < time,
                (QAConversation.last_message_at == time) & (QAConversation.id < cid),
            )
        )
    q = request.args.get("q", "").strip()[:200]
    if q:
        hits = db.select(QALog.conversation_id).where(QALog.question.icontains(q, autoescape=True))
        query = query.where(
            or_(QAConversation.title.icontains(q, autoescape=True), QAConversation.id.in_(hits))
        )
    if request.args.get("knowledge_base_id"):
        query = query.where(
            QAConversation.knowledge_base_id == svc.uuid_value(request.args["knowledge_base_id"])
        )
    rows = db.session.scalars(
        query.order_by(QAConversation.last_message_at.desc(), QAConversation.id.desc()).limit(
            size + 1
        )
    ).all()
    more, rows = len(rows) > size, rows[:size]
    next_cursor = (
        signer.dumps([rows[-1].last_message_at.isoformat(), str(rows[-1].id)]) if more else None
    )
    return success({"items": [svc.conversation_data(c) for c in rows], "next_cursor": next_cursor})


@conversations.get("/web/conversations")
@page_required("/qa")
def web_history():
    svc.wake_worker()
    return history(
        db.select(QAConversation).where(
            QAConversation.user_id == g.user.id,
            QAConversation.source_type == "WEB",
            QAConversation.deleted_at.is_(None),
        )
    )


@conversations.get("/web/conversations/<uuid:cid>")
@page_required("/qa")
def web_detail(cid):
    return success(svc.conversation_data(svc.get_conversation(cid, user_id=g.user.id)))


def turns(c, *, robot=False):
    size = number("page_size", 30, 100)
    query = db.select(QALog).where(QALog.conversation_id == c.id)
    if request.args.get("before"):
        query = query.where(QALog.turn_no < number("before", 1, 2_147_483_647))
    rows = db.session.scalars(query.order_by(QALog.turn_no.desc()).limit(size + 1)).all()
    more, rows = len(rows) > size, rows[:size]
    return success(
        {
            "items": [svc.turn_data(row, robot=robot) for row in reversed(rows)],
            "next_before": rows[-1].turn_no if more else None,
            "conversation": svc.conversation_data(c),
        }
    )


@conversations.get("/web/conversations/<uuid:cid>/turns")
@page_required("/qa")
def web_turns(cid):
    svc.wake_worker()
    return turns(svc.get_conversation(cid, user_id=g.user.id))


def one_turn(c, tid, *, robot=False):
    log = db.session.scalar(db.select(QALog).where(QALog.id == tid, QALog.conversation_id == c.id))
    if not log:
        raise ApiError("问答不存在", 404)
    svc.wake_worker()
    return success(svc.turn_data(log, robot=robot))


@conversations.get("/web/conversations/<uuid:cid>/turns/<uuid:tid>")
@page_required("/qa")
def web_turn(cid, tid):
    return one_turn(svc.get_conversation(cid, user_id=g.user.id), tid)


@conversations.get("/robot/conversations/<uuid:cid>/turns/<uuid:tid>")
@limiter.limit("120 per minute")
def robot_turn(cid, tid):
    robot = robot_identity()
    c = svc.get_conversation(cid, robot_id=robot.id)
    svc.writable(c, robot)
    return one_turn(c, tid, robot=True)


@conversations.delete("/web/conversations/<uuid:cid>")
@page_required("/qa")
def web_delete(cid):
    return success(svc.delete_conversation(cid, user_id=g.user.id))


@conversations.delete("/robot/conversations/<uuid:cid>")
def robot_delete(cid):
    return success(svc.delete_conversation(cid, robot_id=robot_identity().id))


@conversations.post("/web/conversations/<uuid:cid>/turns/<uuid:tid>/retry")
@page_required("/qa")
@limiter.limit("20 per minute", key_func=lambda: str(g.user.id))
def web_retry(cid, tid):
    log = svc.retry_turn(cid, tid, user_id=g.user.id)
    svc.wake_worker()
    return success(svc.turn_data(log)), 202


@conversations.post("/robot/conversations/<uuid:cid>/turns/<uuid:tid>/retry")
@limiter.limit("20 per minute")
def robot_retry(cid, tid):
    robot = robot_identity()
    log = svc.retry_turn(cid, tid, robot_id=robot.id)
    # Releasing a read-only retry transaction is also necessary before a worker can claim.
    db.session.commit()
    return success(wait_for_answer(cid, log.id, robot.id))


@conversations.get("/admin/robot-chat/robots")
@page_required("/robot-qa")
def simulator_robots():
    from ...application.robots.service import robot_data

    result = db.paginate(
        db.select(Robot).order_by(Robot.name, Robot.id),
        page=number("page", 1, 100000),
        per_page=number("page_size", 100, 100),
        error_out=False,
    )
    return success({"items": [robot_data(r) for r in result.items], "total": result.total})


@conversations.get("/admin/robot-chat/robots/<uuid:rid>/conversations")
@page_required("/robot-qa")
def simulator_history(rid):
    from ...application.robots.service import find_robot

    find_robot(rid)
    return history(
        db.select(QAConversation).where(
            QAConversation.robot_id == rid,
            QAConversation.source_type == "ROBOT",
            QAConversation.deleted_at.is_(None),
        )
    )


@conversations.get("/admin/robot-chat/robots/<uuid:rid>/conversations/<uuid:cid>/turns")
@page_required("/robot-qa")
def simulator_turns(rid, cid):
    # Read closed sessions too, while preserving robot ownership and soft deletion.
    return turns(svc.get_conversation(cid, robot_id=rid), robot=True)


def owners(model):
    field = QAConversation.user_id if model is User else QAConversation.robot_id
    counts = (
        db.select(
            field.label("owner_id"),
            func.count().label("conversation_count"),
            func.sum(QAConversation.next_turn_no - 1).label("turn_count"),
        )
        .group_by(field)
        .subquery()
    )
    query = db.select(model, counts.c.conversation_count, counts.c.turn_count).join(
        counts, counts.c.owner_id == model.id
    )
    name = model.display_name if model is User else model.name
    identity = model.username if model is User else model.serial_no
    q = request.args.get("q", "").strip()[:200]
    if q:
        query = query.where(
            or_(name.icontains(q, autoescape=True), identity.icontains(q, autoescape=True))
        )
    page, size = number("page", 1, 100000), number("page_size", 30, 100)
    total = db.session.scalar(db.select(func.count()).select_from(query.subquery()))
    rows = db.session.execute(
        query.order_by(name, model.id).offset((page - 1) * size).limit(size)
    ).all()
    return success(
        {
            "items": [
                {
                    "id": str(owner.id),
                    "name": (owner.display_name or owner.username)
                    if model is User
                    else (owner.name or owner.serial_no),
                    "identity": owner.username if model is User else owner.serial_no,
                    "status": owner.status,
                    "conversation_count": count,
                    "turn_count": turns_count,
                }
                for owner, count, turns_count in rows
            ],
            "total": total,
            "page": page,
            "page_size": size,
        }
    )


@conversations.get("/admin/qa-users")
@page_required("/qa-logs")
def qa_users():
    return owners(User)


@conversations.get("/admin/qa-robots")
@page_required("/qa-logs")
def qa_robots():
    return owners(Robot)


@conversations.get("/admin/qa-conversations")
@page_required("/qa-logs")
def admin_history():
    source = request.args.get("source_type")
    if source not in {"WEB", "ROBOT"}:
        raise ApiError("请选择用户或机器人来源", 422)
    key, other = ("user_id", "robot_id") if source == "WEB" else ("robot_id", "user_id")
    if request.args.get(other):
        raise ApiError("请选择单一的历史归属对象", 422)
    query = db.select(QAConversation).where(
        QAConversation.source_type == source,
        getattr(QAConversation, key) == svc.uuid_value(request.args.get(key)),
    )
    deleted = request.args.get("deleted", "")
    if deleted not in {"", "true", "false"}:
        raise ApiError("删除状态不正确", 422)
    if deleted:
        query = query.where(
            QAConversation.deleted_at.is_not(None)
            if deleted == "true"
            else QAConversation.deleted_at.is_(None)
        )
    return history(query)


@conversations.get("/admin/qa-conversations/<uuid:cid>")
@page_required("/qa-logs")
def admin_detail(cid):
    return success(svc.conversation_data(svc.get_conversation(cid, admin=True)))


@conversations.get("/admin/qa-conversations/<uuid:cid>/turns")
@page_required("/qa-logs")
def admin_turns(cid):
    return turns(svc.get_conversation(cid, admin=True))


@conversations.get("/admin/qa-conversations/<uuid:cid>/export")
@page_required("/qa-logs")
def admin_export(cid):
    from ...application.conversations.export import DOCX_TYPE, export_conversation

    content, filename = export_conversation(cid)
    return send_file(
        BytesIO(content),
        mimetype=DOCX_TYPE,
        as_attachment=True,
        download_name=filename,
        conditional=False,
        etag=False,
    )
