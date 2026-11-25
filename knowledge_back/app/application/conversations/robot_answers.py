"""Wait within a robot HTTP request while durable, fenced work runs independently."""

from time import monotonic, sleep

from flask import current_app

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import QALog, now
from . import service as svc


def wait_for_answer(conversation_id, turn_id, robot_id):
    from ...workers.qa_worker import schedule_turn

    app = current_app._get_current_object()
    deadline = monotonic() + app.config["ROBOT_ANSWER_WAIT_SECONDS"]
    db.session.rollback()
    while True:
        # All locks are short-lived and released before waiting or running a model.
        # Revalidate even cached answers so rebinding/deletion cannot leak stale results.
        robot = svc.lock_robot(robot_id)
        svc.robot_ready(robot)
        conversation = svc.get_conversation(conversation_id, robot_id=robot_id, lock=True)
        svc.writable(conversation, robot)
        log = db.session.scalar(
            db.select(QALog)
            .where(
                QALog.id == turn_id,
                QALog.conversation_id == conversation_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if log is None:
            raise ApiError("问答不存在", 404)
        if log.status not in svc.INFLIGHT:
            result = {
                "conversation": svc.conversation_data(conversation),
                **svc.turn_data(log, robot=True),
            }
            result.pop("poll_after_ms", None)
            db.session.commit()
            return result
        eligible = (
            log.status == "PENDING"
            or db.session.scalar(
                db.select(QALog.id).where(
                    QALog.id == turn_id,
                    QALog.lease_expires_at < now(),
                )
            )
            is not None
        )
        db.session.rollback()
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ApiError("等待回答超时，请使用相同 request_id 重发原问题获取结果", 504, 50401)
        if eligible:
            schedule_turn(app, turn_id)
        sleep(min(0.25, remaining))
