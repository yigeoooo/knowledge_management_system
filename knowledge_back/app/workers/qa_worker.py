"""PostgreSQL-backed question worker with renewable, fenced execution leases."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from flask import current_app
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ..application.conversations.memory import prepare_context
from ..application.conversations.service import lock_robot, user_ready, writable
from ..application.prompts.registry import prompt_scope, published_snapshot
from ..application.qa.workflow import answer_question
from ..core.extensions import db
from ..core.http import ApiError
from ..entities import QAConversation, QALog, now
from ..integrations.ai.chat_adapter import ChatError
from ..integrations.ai.embedding_adapter import EmbeddingError

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="qa-worker")
_guard = Lock()
_running = set()
_turn_tasks = {}


def _locked_turn(turn_id, *, skip=False):
    # Read IDs without holding child locks, then consistently lock parent -> child.
    identity = db.session.execute(
        db.select(QALog.conversation_id, QALog.robot_id).where(QALog.id == turn_id)
    ).first()
    if not identity or not identity.conversation_id:
        return None, None, None
    robot = lock_robot(identity.robot_id, skip_locked=skip) if identity.robot_id else None
    if identity.robot_id and robot is None:
        return None, None, None
    c = db.session.scalar(
        db.select(QAConversation)
        .where(QAConversation.id == identity.conversation_id)
        .with_for_update(skip_locked=skip)
        .execution_options(populate_existing=True)
    )
    if not c:
        return None, None, None
    log = db.session.scalar(
        db.select(QALog)
        .where(QALog.id == turn_id)
        .with_for_update(skip_locked=skip)
        .execution_options(populate_existing=True)
    )
    return c, log, robot


def _validate(c, robot):
    writable(c, robot)
    if c.user_id:
        user_ready(c.user_id)


def claim(turn_id=None):
    expired = (QALog.status == "PROCESSING") & (QALog.lease_expires_at < now())
    query = db.select(QALog.id).where(
        QALog.conversation_id.is_not(None),
        or_(QALog.status == "PENDING", expired),
    )
    if turn_id is not None:
        query = query.where(QALog.id == turn_id)
    candidates = db.session.scalars(query.order_by(QALog.created_at).limit(30)).all()
    db.session.rollback()
    for tid in candidates:
        c, log, robot = _locked_turn(tid, skip=True)
        if not log:
            db.session.rollback()
            continue
        # Compare timestamps in SQL to avoid SQLite naive/aware differences.
        eligible = db.session.scalar(
            db.select(QALog.id).where(
                QALog.id == tid,
                or_(
                    QALog.status == "PENDING",
                    (QALog.status == "PROCESSING") & (QALog.lease_expires_at < now()),
                ),
            )
        )
        if not eligible:
            db.session.rollback()
            continue
        try:
            _validate(c, robot)
        except ApiError as error:
            log.status, log.error_message = "CANCELLED", error.message
            log.lease_token, log.lease_expires_at = None, None
            db.session.commit()
            continue
        if log.attempts >= current_app.config["QA_MAX_ATTEMPTS"]:
            log.status, log.error_message = "FAILED", "回答任务多次中断，请点击重试"
            log.lease_token, log.lease_expires_at = None, None
            db.session.commit()
            continue
        if log.prompt_snapshot is None:
            try:
                log.prompt_snapshot = published_snapshot()
            except RuntimeError:
                log.status, log.error_message = "FAILED", "提示词配置缺失，请联系管理员升级数据库"
                log.lease_token, log.lease_expires_at = None, None
                db.session.commit()
                continue
        token = uuid4()
        log.status, log.lease_token = "PROCESSING", token
        log.lease_expires_at = now() + timedelta(seconds=current_app.config["QA_LEASE_SECONDS"])
        log.attempts += 1
        log.error_message = None
        db.session.commit()
        return tid, token
    return None


def _heartbeat(app, tid, token, stop):
    while not stop.wait(20):
        with app.app_context():
            try:
                result = db.session.execute(
                    db.update(QALog)
                    .where(
                        QALog.id == tid,
                        QALog.status == "PROCESSING",
                        QALog.lease_token == token,
                    )
                    .values(
                        lease_expires_at=now() + timedelta(seconds=app.config["QA_LEASE_SECONDS"])
                    )
                )
                db.session.commit()
                if result.rowcount != 1:
                    return
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.warning("qa lease renewal failed turn=%s", tid, exc_info=True)


def finish(tid, token, values):
    from ..api.qa.controller import _verify_current

    c, log, robot = _locked_turn(tid)
    if not log or log.status != "PROCESSING" or log.lease_token != token:
        db.session.rollback()
        return False
    still_leased = db.session.scalar(
        db.select(QALog.id).where(QALog.id == tid, QALog.lease_expires_at > now())
    )
    if not still_leased:
        db.session.rollback()
        return False
    try:
        _validate(c, robot)
        if values.get("status") not in {"FAILED", "CANCELLED"}:
            _verify_current(c.knowledge_base_id, values.get("sources", []))
    except ApiError as error:
        values = {"status": "CANCELLED", "error_message": error.message}
    for key, value in values.items():
        setattr(log, key, value)
    log.lease_token, log.lease_expires_at = None, None
    db.session.commit()
    return True


def process_one(app, turn_id=None):
    with app.app_context():
        job = claim(turn_id)
        if not job:
            return False
        tid, token = job
        stop = Event()
        heartbeat = None
        if not app.testing:
            heartbeat = Thread(target=_heartbeat, args=(app, tid, token, stop), daemon=True)
            heartbeat.start()
        started = monotonic()
        try:
            log = db.session.get(QALog, tid)
            cid, number, question, base_id, anchor = (
                log.conversation_id,
                log.turn_no,
                log.question,
                log.knowledge_base_id,
                log.suggestion_anchor,
            )
            request_id = log.request_id
            app.logger.info("qa task started turn=%s conversation=%s request_id=%s", tid, cid, request_id)
            snapshot = log.context_snapshot
            prompts = log.prompt_snapshot
            robot = log.source_type == "ROBOT"
            db.session.rollback()
            from langchain_core.runnables import RunnableLambda

            from ..application.qa.observability import record_turn

            def execute(_):
                nonlocal snapshot
                if snapshot is None:
                    snapshot = RunnableLambda(lambda _: prepare_context(
                        cid, number, turn_id=tid, lease_token=token)).invoke(
                            {}, config={"run_name": "prepare_memory"})
                    saved = db.session.execute(
                        db.update(QALog)
                        .where(
                            QALog.id == tid,
                            QALog.lease_token == token,
                            QALog.status == "PROCESSING",
                            QALog.lease_expires_at > now(),
                        )
                        .values(context_snapshot=snapshot)
                    )
                    db.session.commit()
                    if saved.rowcount != 1:
                        return None
                return answer_question(
                    question,
                    base_id,
                    snapshot,
                    anchor,
                    robot=robot,
                    trace_context={
                        "conversation_id": cid,
                        "turn_id": tid,
                        "knowledge_base_id": base_id,
                        "request_id": request_id,
                    },
                )

            with prompt_scope(prompts):
                values = record_turn(execute, metadata={
                    "conversation_id": cid, "turn_id": tid, "knowledge_base_id": base_id,
                }, robot=robot)
            if values is None:
                return True
            values["latency_ms"] = int((monotonic() - started) * 1000)
            saved = finish(tid, token, values)
            app.logger.info("qa task finished turn=%s status=%s saved=%s duration=%sms",
                            tid, values.get("status"), saved, values["latency_ms"])
        except Exception as error:
            app.logger.exception("qa task failed turn=%s type=%s", tid, type(error).__name__)
            db.session.rollback()
            message = (
                error.message
                if isinstance(error, ApiError)
                else (
                    str(error)
                    if isinstance(error, (ChatError, EmbeddingError))
                    else "问答暂时不可用，请稍后重试"
                )
            )
            finish(
                tid,
                token,
                {
                    "status": "FAILED",
                    "error_message": message,
                    "execution_trace": getattr(error, "execution_trace", None),
                    "latency_ms": int((monotonic() - started) * 1000),
                },
            )
        finally:
            stop.set()
            if heartbeat:
                heartbeat.join(timeout=1)
        return True


def schedule_turn(app, turn_id):
    """Run this receipt without depending on the web queue scheduler being enabled."""
    key = (id(app), turn_id)
    with _guard:
        task = _turn_tasks.get(key)
        if task is not None and not task.done():
            return task
        task = _executor.submit(process_one, app, turn_id)
        _turn_tasks[key] = task

    def completed(future):
        with _guard:
            if _turn_tasks.get(key) is future:
                _turn_tasks.pop(key, None)
        if not future.cancelled() and future.exception() is not None:
            error = future.exception()
            app.logger.error(
                "qa task execution failed turn=%s type=%s",
                turn_id,
                type(error).__name__,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(completed)
    return task


def run_worker(app, *, once=False, interval=1):
    import time

    count = 0
    while True:
        worked = process_one(app)
        if worked:
            count += 1
        if once:
            return count
        if not worked:
            time.sleep(interval)


def schedule_worker(app):
    """One scheduler per Flask app. Periodic scanning also recovers expired leases."""
    with _guard:
        if id(app) in _running:
            return
        _running.add(id(app))

    # A daemon avoids blocking Flask shutdown; production uses the CLI process.
    def loop():
        import time

        while True:
            try:
                with app.app_context():
                    ready = db.session.scalar(
                        db.select(QALog.id)
                        .where(
                            QALog.conversation_id.is_not(None),
                            or_(
                                QALog.status == "PENDING",
                                (QALog.status == "PROCESSING") & (QALog.lease_expires_at < now()),
                            ),
                        )
                        .limit(1)
                    )
                if ready:
                    # Bound concurrency and wait before scheduling more work.
                    futures = [_executor.submit(process_one, app) for _ in range(2)]
                    for future in futures:
                        future.result()
            except Exception as error:
                app.logger.exception("qa scheduler failed type=%s", type(error).__name__)
            time.sleep(1)

    Thread(target=loop, daemon=True, name="qa-scheduler").start()
