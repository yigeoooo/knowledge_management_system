"""Real PostgreSQL locking checks in an isolated, disposable schema.

Run KBS_POSTGRES_TESTS=1 pytest tests/test_conversations_postgres.py.
The configured database's business tables are never used by these tests.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from app import create_app
from app.entities import KnowledgeBase, QALog, Robot
from app.extensions import db
from app.workers import qa_worker

pytestmark = pytest.mark.skipif(
    os.getenv("KBS_POSTGRES_TESTS") != "1", reason="explicit local PostgreSQL integration run"
)


@pytest.fixture
def pg_app():
    from app.core.config import configuration

    schema = "qa_test_" + uuid4().hex
    url = configuration({"JWT_SECRET_KEY": "postgres-isolated-test-secret-123456"})[
        "SQLALCHEMY_DATABASE_URI"
    ]
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": url,
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"options": f"-c search_path={schema},public"}
            },
            "JWT_SECRET_KEY": "postgres-isolated-test-secret-123456",
            "QA_WORKER_AUTOSTART": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    try:
        with app.app_context():
            # Explicit schema check prevents accidental use of the business schema.
            assert db.session.scalar(text("SELECT current_schema()")) == schema
            db.metadata.create_all(db.engine, checkfirst=False)
            a, b = KnowledgeBase(code="a", name="A"), KnowledgeBase(code="b", name="B")
            db.session.add_all([a, b])
            db.session.flush()
            r = Robot(serial_no="pg-robot", knowledge_base_id=a.id, binding_version=1)
            db.session.add(r)
            db.session.commit()
            app.config["TEST_IDS"] = (r.id, a.id, b.id)
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_simultaneous_first_request_is_one_conversation_and_turn(pg_app, monkeypatch):
    gate = Barrier(2)
    answers = []

    def answer(*args, **kwargs):
        answers.append(args)
        return {"status": "SUCCESS", "answer": "唯一答案", "sources": []}

    monkeypatch.setattr(qa_worker, "answer_question", answer)

    def submit():
        with pg_app.test_client() as client:
            gate.wait(timeout=5)
            result = client.post(
                "/api/v1/robot/query",
                json={"serial_no": "pg-robot", "question": "如何启动？", "request_id": "same"},
            )
            assert result.status_code == 200, result.json
            return result.json["data"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0]["turn_id"] == results[1]["turn_id"]
    assert results[0]["conversation_id"] == results[1]["conversation_id"]
    with pg_app.app_context():
        assert db.session.query(QALog).count() == 1
    assert len(answers) == 1
    assert all(result["answer"] == "唯一答案" for result in results)


def test_rebind_during_model_call_fences_writeback(pg_app, monkeypatch):
    started, release = Event(), Event()

    def slow_answer(*args, **kwargs):
        started.set()
        assert release.wait(timeout=10)
        return {"status": "SUCCESS", "answer": "stale", "sources": []}

    monkeypatch.setattr(qa_worker, "answer_question", slow_answer)

    def submit():
        with pg_app.test_client() as client:
            return client.post(
                "/api/v1/robot/query",
                json={"serial_no": "pg-robot", "question": "如何启动？", "request_id": "rebind"},
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(submit)
        try:
            assert started.wait(timeout=10)
            with pg_app.app_context():
                from app.application.conversations.service import lock_robot, rebind_robot

                log_id = db.session.scalar(db.select(QALog.id))
                robot_id, _, base_b = pg_app.config["TEST_IDS"]
                rebind_robot(lock_robot(robot_id), base_b, 1)
                db.session.commit()
            response = future.result(timeout=5)
            assert response.status_code == 409 and response.json["code"] == 40912
            task = qa_worker.schedule_turn(pg_app, log_id)
        finally:
            release.set()
        task.result(timeout=5)
    with pg_app.app_context():
        log = db.session.get(QALog, log_id)
        assert log.status == "CANCELLED" and log.answer is None
