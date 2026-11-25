"""Durable experiments with renewable fenced leases and per-pair checkpoints."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Event, Lock, Thread
from time import perf_counter, sleep
from uuid import UUID, uuid4

from flask import current_app
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from ..application.evaluations.service import digest, environment
from ..application.prompts.registry import prompt_scope
from ..application.qa.evaluation import evaluate_input, metrics
from ..core.extensions import db
from ..entities import EvaluationRun, KnowledgeBase, now
from ..integrations.ai.chat_adapter import ChatError

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evaluation-worker")
_guard = Lock()
_running = set()


def claim():
    row = db.session.scalar(
        db.select(EvaluationRun)
        .where(
            or_(
                EvaluationRun.status == "PENDING",
                (EvaluationRun.status == "RUNNING") & (EvaluationRun.lease_expires_at < now()),
            )
        )
        .order_by(EvaluationRun.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        db.session.rollback()
        return None
    if row.attempts >= 3:
        row.status, row.error_message = "FAILED", "评测多次中断，请重新发起实验"
        row.lease_token = row.lease_expires_at = None
        db.session.commit()
        return False
    token = uuid4()
    row.status, row.lease_token, row.lease_expires_at = (
        "RUNNING",
        token,
        now() + timedelta(seconds=180),
    )
    row.attempts += 1
    db.session.commit()
    return row.id, token, deepcopy(row.snapshot), deepcopy(row.results)


def update(id, token, **values):
    result = db.session.execute(
        db.update(EvaluationRun)
        .where(
            EvaluationRun.id == id,
            EvaluationRun.status == "RUNNING",
            EvaluationRun.lease_token == token,
            EvaluationRun.lease_expires_at > now(),
        )
        .values(**values)
    )
    db.session.commit()
    return result.rowcount == 1


def heartbeat(app, id, token, stop):
    while not stop.wait(20):
        with app.app_context():
            try:
                if not update(id, token, lease_expires_at=now() + timedelta(seconds=180)):
                    return
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.warning("evaluation lease renewal failed run=%s", id, exc_info=True)


def verify_environment(snapshot):
    base_id = UUID(snapshot["knowledge_base_id"])
    base = db.session.get(KnowledgeBase, base_id)
    valid = (
        base is not None
        and base.status == "active"
        and base.code == snapshot["knowledge_base_code"]
    )
    match = digest(environment(base_id)) == snapshot["environment_hash"]
    db.session.rollback()
    if not valid or not match:
        raise RuntimeError("知识库、索引或运行配置已变化，本次对比已停止；请重新发起实验")


def evaluate_arm(example, prompts, trace_context=None):
    started = perf_counter()
    current_app.logger.info("evaluation arm started context=%s", trace_context)
    try:
        with prompt_scope(prompts):
            output = evaluate_input(example["inputs"], trace_context=trace_context)
        scores = metrics(output, example["reference"])
        current_app.logger.info("evaluation arm completed context=%s duration=%.2fms",
                                trace_context, (perf_counter() - started) * 1000)
        return {"outputs": output, "scores": scores, "error": None}
    except Exception as error:
        current_app.logger.exception("evaluation arm failed context=%s type=%s",
                                     trace_context, type(error).__name__)
        db.session.rollback()
        trace = getattr(error, "execution_trace", None) or {}
        output = {key: value for key, value in {
            "run_id": trace.get("run_id"), "prompt_versions": trace.get("prompts"),
        }.items() if value is not None}
        return {"outputs": output, "scores": {}, "error": type(error).__name__,
                "error_message": str(error)[:500] if isinstance(error, ChatError)
                else "评测调用失败，请稍后重试"}


def process_one(app):
    with app.app_context():
        job = claim()
        if job is None:
            return False
        if job is False:
            return True
        id, token, snapshot, results = job
        app.logger.info("evaluation task started run=%s questions=%s", id, len(snapshot["examples"]))
        stop = Event()
        thread = Thread(target=heartbeat, args=(app, id, token, stop), daemon=True)
        if not app.testing:
            thread.start()
        try:
            verify_environment(snapshot)
            retry_mode = any("retry_pending" in r for r in results)
            for index, example in enumerate(snapshot["examples"]):
                existing = next((r for r in results if r["id"] == example["id"]), None)
                if retry_mode:
                    if not existing or not existing.get("retry_pending"):
                        continue
                    pair = deepcopy(existing)
                    needed = set(pair["retry_pending"])
                else:
                    if existing:
                        continue
                    pair = {"id": example["id"], "name": example["name"], "review": None}
                    needed = {"baseline", "candidate"}
                # Alternate order to reduce a systematic timing/order advantage.
                for arm in (
                    ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
                ):
                    if arm not in needed:
                        continue
                    verify_environment(snapshot)
                    pair[arm] = evaluate_arm(example, snapshot[arm], {"evaluation_run_id": str(id), "evaluation_example_id": example["id"], "evaluation_arm": arm})
                    verify_environment(snapshot)
                    if retry_mode:
                        pair["retry_pending"].remove(arm)
                        results = [deepcopy(pair) if r["id"] == example["id"] else r for r in results]
                        # Checkpoint each retried arm so lease recovery keeps successful calls.
                        if not update(id, token, results=results):
                            return True
                if not retry_mode:
                    results.append(pair)
                    if not update(id, token, results=results):
                        return True
            failed = len(results) != len(snapshot["examples"]) or any(
                r.get("retry_pending") or not r.get(a) or r[a].get("error")
                for r in results for a in ("baseline", "candidate")
            )
            saved = update(
                id,
                token,
                status="FAILED" if failed else "COMPLETED",
                error_message="部分样本调用失败，失败样本不参与质量均值，请查看逐题结果"
                if failed
                else None,
                lease_token=None,
                lease_expires_at=None,
            )
            app.logger.info("evaluation task finished run=%s status=%s saved=%s",
                            id, "FAILED" if failed else "COMPLETED", saved)
        except Exception as error:
            app.logger.exception("evaluation task failed run=%s type=%s", id, type(error).__name__)
            db.session.rollback()
            message = (
                str(error) if isinstance(error, RuntimeError) else "评测执行失败，请检查服务后重试"
            )
            update(
                id,
                token,
                status="FAILED",
                error_message=message[:500],
                lease_token=None,
                lease_expires_at=None,
            )
        finally:
            stop.set()
            if thread.is_alive():
                thread.join(timeout=1)
        return True


def schedule_worker(app):
    with _guard:
        if id(app) in _running:
            return
        _running.add(id(app))

    def drain():
        try:
            while process_one(app):
                pass
        finally:
            with _guard:
                _running.discard(id(app))

    _pool.submit(drain)


def run_worker(app, once=False):
    count = 0
    while True:
        processed = process_one(app)
        count += int(processed)
        if once and not processed:
            return count
        if not processed:
            sleep(2)
