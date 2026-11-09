from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import test_conversations as conversation_tests

from app.entities import QALog
from app.extensions import db
from app.workers import qa_worker

setup = conversation_tests.setup


PAYLOAD = {"serial_no": "conversation-robot", "question": "如何启动？", "request_id": "sync-first"}


def test_robot_post_waits_for_final_answer(app, setup, monkeypatch):
    started, release = Event(), Event()

    def answer(*args, **kwargs):
        started.set()
        assert release.wait(timeout=10)
        return {"status": "SUCCESS", "answer": "按下启动按钮", "sources": []}

    monkeypatch.setattr(qa_worker, "answer_question", answer)
    with ThreadPoolExecutor(max_workers=1) as pool:

        def submit():
            with app.test_client() as client:
                return client.post("/api/v1/robot/query", json=PAYLOAD)

        future = pool.submit(submit)
        try:
            assert started.wait(timeout=3)
            assert not future.done()
        finally:
            release.set()
        response = future.result(timeout=5)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["answer"] == "按下启动按钮"
    assert data["status"] == "SUCCESS"
    assert data["conversation_id"] == data["conversation"]["id"]
    assert "poll_after_ms" not in data


def test_wait_timeout_can_resume_by_reposting_same_request(app, client, setup, monkeypatch):
    app.config["ROBOT_ANSWER_WAIT_SECONDS"] = 0.1
    release = Event()
    calls = []

    def answer(*args, **kwargs):
        calls.append(args)
        assert release.wait(timeout=10)
        return {"status": "SUCCESS", "answer": "原问题的答案", "sources": []}

    monkeypatch.setattr(qa_worker, "answer_question", answer)
    try:
        response = client.post("/api/v1/robot/query", json=PAYLOAD)
        assert response.status_code == 504
        assert response.json["code"] == 50401
        with app.app_context():
            log = db.session.scalar(
                db.select(QALog).where(QALog.request_id == PAYLOAD["request_id"])
            )
            turn_id = log.id
        task = qa_worker.schedule_turn(app, turn_id)
    finally:
        release.set()
    task.result(timeout=5)
    result = client.post("/api/v1/robot/query", json=PAYLOAD)
    assert result.status_code == 200
    assert result.json["data"]["turn_id"] == str(turn_id)
    assert result.json["data"]["answer"] == "原问题的答案"
    assert len(calls) == 1
    with app.app_context():
        assert db.session.query(QALog).count() == 1


def test_robot_retry_waits_and_preserves_turn(app, client, setup, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("provider private details")

    monkeypatch.setattr(qa_worker, "answer_question", fail)
    response = client.post("/api/v1/robot/query", json=PAYLOAD)
    assert response.status_code == 200
    failed = response.json["data"]
    assert failed["status"] == "FAILED"
    assert "private" not in failed["error_message"]
    monkeypatch.setattr(
        qa_worker,
        "answer_question",
        lambda *args, **kwargs: {
            "status": "SUCCESS",
            "answer": "重试成功",
            "sources": [],
        },
    )
    result = client.post(
        f"/api/v1/robot/conversations/{failed['conversation_id']}/turns/{failed['turn_id']}/retry",
        headers={"X-Robot-Serial": PAYLOAD["serial_no"]},
        json={},
    )
    assert result.status_code == 200
    assert result.json["data"]["status"] == "SUCCESS"
    assert result.json["data"]["turn_id"] == failed["turn_id"]
    assert result.json["data"]["request_id"] == PAYLOAD["request_id"]
    assert result.json["data"]["turn_no"] == 1
    with app.app_context():
        assert db.session.get(QALog, UUID(failed["turn_id"])).answer == "重试成功"
