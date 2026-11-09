"""Exercise real conversation endpoints and worker leases with isolated AI calls."""

from datetime import timedelta
from uuid import uuid4

import pytest
from test_knowledge_bases import login

from app.entities import KnowledgeBase, QALog, Robot, now
from app.extensions import db
from app.workers import qa_worker


@pytest.fixture
def setup(app, client, monkeypatch):
    with app.app_context():
        base = KnowledgeBase(code="conversation-base", name="会话资料")
        other = KnowledgeBase(code="conversation-other", name="另一知识库")
        db.session.add_all([base, other])
        db.session.flush()
        robot = Robot(
            serial_no="conversation-robot",
            name="会话设备",
            knowledge_base_id=base.id,
            binding_version=1,
        )
        db.session.add(robot)
        db.session.commit()
        ids = {"base": str(base.id), "other": str(other.id), "robot": str(robot.id)}
    seen = []

    def answer(question, base_id, context, anchor, *, robot=False):
        seen.append((question, str(base_id), context))
        return {
            "status": "SUCCESS",
            "answer": "已核实的答案",
            "sources": [],
            "model_name": "test",
            "retrieval_count": 0,
            "answer_kind": "knowledge",
            "resolved_question": question,
        }

    monkeypatch.setattr(qa_worker, "answer_question", answer)
    return {**ids, "headers": login(client), "seen": seen}


def first(client, setup, question="如何启动设备？", key=None):
    response = client.post(
        "/api/v1/web/conversations",
        headers=setup["headers"],
        json={
            "knowledge_base_id": setup["base"],
            "question": question,
            "request_id": key or str(uuid4()),
        },
    )
    assert response.status_code == 202, response.json
    return response.json["data"]


def test_history_continues_and_separate_conversations_have_no_shared_memory(app, client, setup):
    one = first(client, setup, key="first-question")
    repeat = first(client, setup, key="first-question")
    assert repeat["conversation_id"] == one["conversation_id"]
    assert repeat["turn_id"] == one["turn_id"]
    assert qa_worker.process_one(app)
    cid = one["conversation_id"]
    response = client.post(
        f"/api/v1/web/conversations/{cid}/turns",
        headers=setup["headers"],
        json={"question": "刚才第二步呢？", "request_id": "followup", "expected_last_turn_no": 1},
    )
    assert response.status_code == 202
    assert qa_worker.process_one(app)
    assert setup["seen"][1][2]["turns"][0]["question"] == "如何启动设备？"
    first(client, setup, question="新话题")
    assert qa_worker.process_one(app)
    assert setup["seen"][2][2]["turns"] == []
    history = client.get(f"/api/v1/web/conversations/{cid}/turns", headers=setup["headers"]).json[
        "data"
    ]
    assert [r["turn_no"] for r in history["items"]] == [1, 2]
    assert history["items"][1]["answer"] == "已核实的答案"


def test_soft_delete_hides_personal_history_but_admin_keeps_full_conversation(app, client, setup):
    item = first(client, setup)
    cid = item["conversation_id"]
    response = client.delete(f"/api/v1/web/conversations/{cid}", headers=setup["headers"])
    assert response.status_code == 200
    assert (
        client.delete(f"/api/v1/web/conversations/{cid}", headers=setup["headers"]).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/web/conversations/{cid}/turns", headers=setup["headers"]).status_code
        == 404
    )
    assert (
        client.get("/api/v1/web/conversations", headers=setup["headers"]).json["data"]["items"]
        == []
    )
    admin = client.get(f"/api/v1/admin/qa-conversations/{cid}/turns", headers=setup["headers"])
    assert admin.json["data"]["conversation"]["deleted_at"]
    assert admin.json["data"]["items"][0]["status"] == "CANCELLED"
    assert not qa_worker.process_one(app)


def test_other_user_cannot_read_post_delete_or_poll(app, client, setup):
    one = first(client, setup)
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    headers = login(client, "reader", "Reader-Password-2026!")
    path = f"/api/v1/web/conversations/{one['conversation_id']}"
    for suffix in ("", "/turns", f"/turns/{one['turn_id']}"):
        assert client.get(path + suffix, headers=headers).status_code == 404
    assert client.delete(path, headers=headers).status_code == 404
    assert (
        client.post(
            path + "/turns", headers=headers, json={"question": "越权", "request_id": "stolen"}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/admin/qa-users", headers=headers).status_code == 403


def robot_first(client, key="robot-first"):
    return client.post(
        "/api/v1/robot/query",
        json={"serial_no": "conversation-robot", "question": "设备如何启动？", "request_id": key},
    )


def test_robot_binding_context_and_rebind_closes_old_conversations(app, client, setup):
    result = robot_first(client)
    assert result.status_code == 200, result.json
    one = result.json["data"]
    assert robot_first(client).json["data"]["turn_id"] == one["turn_id"]
    continued = client.post(
        "/api/v1/robot/conversations/query",
        json={
            "serial_no": "conversation-robot",
            "conversation_id": one["conversation_id"],
            "question": "然后呢？",
            "request_id": "robot-next",
        },
    )
    assert continued.status_code == 200
    assert setup["seen"][1][2]["turns"]
    updated = client.put(
        f"/api/v1/robots/{setup['robot']}",
        headers=setup["headers"],
        json={"knowledge_base_id": setup["other"], "expected_binding_version": 1},
    )
    assert updated.status_code == 200, updated.json
    assert updated.json["data"]["binding_version"] == 2
    assert robot_first(client).status_code == 409  # A retry is never a new conversation in B.
    assert (
        client.get(
            f"/api/v1/robot/conversations/{one['conversation_id']}/turns/{one['turn_id']}",
            headers={"X-Robot-Serial": "conversation-robot"},
        ).status_code
        == 409
    )
    new = robot_first(client, "robot-after-rebind").json["data"]
    assert new["conversation_id"] != one["conversation_id"]
    assert new["conversation"]["knowledge_base_id"] == setup["other"]
    assert setup["seen"][-1][2]["turns"] == []
    client.put(
        f"/api/v1/robots/{setup['robot']}",
        headers=setup["headers"],
        json={"knowledge_base_id": setup["base"], "expected_binding_version": 2},
    )
    assert (
        client.post(
            "/api/v1/robot/conversations/query",
            json={
                "serial_no": "conversation-robot",
                "conversation_id": one["conversation_id"],
                "question": "继续",
                "request_id": "after-return",
            },
        ).status_code
        == 409
    )


def test_robot_rejects_missing_or_foreign_ids_and_client_selected_base(app, client, setup):
    assert (
        client.post(
            "/api/v1/robot/query", json={"serial_no": "conversation-robot", "question": "a"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/robot/query",
            json={
                "serial_no": "conversation-robot",
                "question": "a",
                "request_id": "a",
                "knowledge_base_code": "other",
            },
        ).status_code
        == 422
    )
    one = first(client, setup)
    for cid in (None, "bad", one["conversation_id"], str(uuid4())):
        response = client.post(
            "/api/v1/robot/conversations/query",
            json={
                "serial_no": "conversation-robot",
                "conversation_id": cid,
                "question": "a",
                "request_id": str(uuid4()),
            },
        )
        assert response.status_code in {422, 404}


def test_pending_ordering_conflict_and_failed_retry(app, client, setup, monkeypatch):
    one = first(client, setup)
    path = f"/api/v1/web/conversations/{one['conversation_id']}/turns"
    payload = {"request_id": "next", "question": "继续"}
    assert client.post(path, headers=setup["headers"], json=payload).status_code == 409
    monkeypatch.setattr(
        qa_worker,
        "answer_question",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private failure")),
    )
    assert qa_worker.process_one(app)
    failed = client.get(path + f"/{one['turn_id']}", headers=setup["headers"]).json["data"]
    assert failed["status"] == "FAILED"
    assert "private failure" not in failed["error_message"]
    assert (
        client.post(path + f"/{one['turn_id']}/retry", headers=setup["headers"]).status_code == 202
    )
    with app.app_context():
        assert db.session.scalar(db.select(func_count()).select_from(QALog)) == 1


def func_count():
    from sqlalchemy import func

    return func.count()


def test_expired_worker_cannot_overwrite_deleted_or_reclaimed_turn(app, client, setup):
    one = first(client, setup)
    with app.app_context():
        tid, token = qa_worker.claim()
        log = db.session.get(QALog, tid)
        log.lease_expires_at = now() - timedelta(seconds=1)
        db.session.commit()
        tid2, token2 = qa_worker.claim()
        assert tid2 == tid and token2 != token
        assert not qa_worker.finish(
            tid, token, {"status": "SUCCESS", "answer": "stale", "sources": []}
        )
    client.delete(f"/api/v1/web/conversations/{one['conversation_id']}", headers=setup["headers"])
    with app.app_context():
        assert not qa_worker.finish(
            tid, token2, {"status": "SUCCESS", "answer": "late", "sources": []}
        )
        assert db.session.get(QALog, tid).status == "CANCELLED"


def test_admin_owner_list_and_selection(app, client, setup):
    item = first(client, setup)
    owners = client.get("/api/v1/admin/qa-users", headers=setup["headers"]).json["data"]["items"]
    assert len(owners) == 1 and owners[0]["conversation_count"] == 1
    assert (
        client.get(
            "/api/v1/admin/qa-conversations?source_type=WEB", headers=setup["headers"]
        ).status_code
        == 422
    )
    listed = client.get(
        f"/api/v1/admin/qa-conversations?source_type=WEB&user_id={owners[0]['id']}",
        headers=setup["headers"],
    ).json["data"]["items"]
    assert [c["id"] for c in listed] == [item["conversation_id"]]


def test_suggested_question_validation_returns_client_error(client, setup):
    response = client.post(
        "/api/v1/web/conversations",
        headers=setup["headers"],
        json={
            "knowledge_base_id": setup["base"],
            "question": ["invalid"],
            "request_id": "invalid-question",
            "suggestion_token": "token",
        },
    )
    assert response.status_code == 422
