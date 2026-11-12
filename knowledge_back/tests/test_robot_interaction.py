from copy import deepcopy
from uuid import UUID

import pytest
from test_knowledge_bases import login
from test_prompt_evaluations import dataset as dataset_fixture
from test_prompt_evaluations import save

from app.application.conversations import memory
from app.application.prompts.registry import get_prompt, prompt_scope, published_snapshot
from app.application.qa import robot_interaction, workflow
from app.application.qa.retrieval_service import AnswerMaterial
from app.core.extensions import db
from app.entities import EvaluationRun, KnowledgeBase, QALog, Robot
from app.integrations.ai.chat_adapter import ChatError
from app.workers import evaluation_worker


@pytest.fixture
def admin(client):
    return login(client)


dataset = dataset_fixture


@pytest.fixture
def robot_base(app):
    with app.app_context():
        base = db.session.scalar(db.select(KnowledgeBase))
        robot = Robot(serial_no="xiaowei-test", name="测试机器人", knowledge_base_id=base.id,
                      status="active", binding_version=1)
        db.session.add(robot)
        db.session.commit()
        return base.id


@pytest.mark.parametrize(("question", "kind", "answer"), [
    ("你好", "chat", "你好呀，我是小维，很高兴认识你！"),
    ("你叫什么名字", "chat", "我是小维，可以陪你聊天，也可以帮你查资料。"),
    ("为什么会下雨", "general", "空气中的水蒸气凝结成小水滴，聚集变大后落下来，就形成了雨。"),
    ("那里呢", "clarification", "你指的是哪个地方呢？"),
])
def test_direct_interaction_uses_persona_without_retrieval(app, robot_base, monkeypatch, question, kind, answer):
    observed = []
    def complete(prompt, material, **kwargs):
        observed.append(material)
        assert "小维" in prompt and "不声称获取了实时信息" in prompt
        return {"kind": kind, "answer": answer}, "test-chat"
    monkeypatch.setattr(robot_interaction, "complete_json", complete)
    monkeypatch.setattr(workflow, "retrieve_for_answer", lambda *a, **k: pytest.fail("直接交流不能检索"))
    with app.app_context():
        result = workflow.answer_question(question, robot_base, {}, robot=True)
    assert result["answer"] == answer and result["answer_kind"] == kind
    assert result["sources"] == [] and result["retrieval_count"] == 0
    assert result["status"] == "SUCCESS"
    assert result["execution_trace"]["used_prompt_keys"] == ["robot_interaction", "robot_persona"]
    assert {"route_interaction", "direct_answer"} <= {s["name"] for s in result["execution_trace"]["steps"]}
    assert observed[0]["knowledge_base_scope"]["name"]


@pytest.mark.parametrize("topic", ["weather", "other"])
def test_realtime_never_uses_model_invented_live_facts(app, robot_base, monkeypatch, topic):
    monkeypatch.setattr(robot_interaction, "complete_json", lambda *a, **k: (
        {"kind": "realtime", "realtime_topic": topic, "answer": "现在晴天，温度26度，我已经联网查询了。"}, "test"))
    monkeypatch.setattr(workflow, "retrieve_for_answer", lambda *a, **k: pytest.fail("不能用静态资料假装实时查询"))
    with app.app_context():
        result = workflow.answer_question("今天天气怎么样", robot_base, {}, robot=True)
    assert result["answer_kind"] == "realtime" and "小维" in result["answer"]
    assert all(word not in result["answer"] for word in ("26", "晴天", "已经联网"))


@pytest.mark.parametrize("question", ["你好，套票多少钱", "景区雨天是否开放", "那我们八个人多少钱"])
def test_business_branch_preserves_history_and_never_guesses_when_evidence_missing(app, robot_base, monkeypatch, question):
    context = {"summary": "讨论套票", "turns": [{"question": "我们有8个人", "answer": "旧回答：每人99元"}]}
    observed = []
    def classify(prompt, material, **kwargs):
        observed.append(deepcopy(material))
        return {"kind": "knowledge", "answer": "不应该返回的猜测价格"}, "test"
    monkeypatch.setattr(robot_interaction, "complete_json", classify)
    monkeypatch.setattr(memory, "complete_json", lambda *a, **k: ({"resolved_question": question, "clarification": None}, "test"))
    monkeypatch.setattr(workflow, "retrieve_for_answer", lambda *a, **k: AnswerMaterial([], [], {}, 0))
    monkeypatch.setattr(workflow, "generate_answer", lambda *a, **k: pytest.fail("没有证据时不能生成业务事实"))
    with app.app_context():
        result = workflow.answer_question(question, robot_base, context, robot=True)
    assert result["answer_kind"] == "knowledge" and result["status"] == "NO_EVIDENCE"
    assert "99" not in result["answer"] and "猜测" not in result["answer"]
    assert observed[0]["history"] == context


@pytest.mark.parametrize("payload", [{"kind": "unknown"}, {"kind": "general", "answer": ""}, None])
def test_routing_failure_falls_back_to_knowledge(app, robot_base, monkeypatch, payload):
    def classify(*args, **kwargs):
        if payload is None:
            raise ChatError("模型暂时不可用")
        return payload, "test"
    monkeypatch.setattr(robot_interaction, "complete_json", classify)
    monkeypatch.setattr(workflow, "retrieve_for_answer", lambda *a, **k: AnswerMaterial([], [], {}, 0))
    with app.app_context():
        result = workflow.answer_question("产品价格", robot_base, {}, robot=True)
    assert result["answer_kind"] == "knowledge" and result["status"] == "NO_EVIDENCE"
    assert result["execution_trace"]["interaction"]["fallback"]


def test_web_and_old_frozen_robot_turns_keep_previous_path(app, robot_base, monkeypatch):
    monkeypatch.setattr(robot_interaction, "complete_json", lambda *a, **k: pytest.fail("不应新增分流调用"))
    monkeypatch.setattr(workflow, "retrieve_for_answer", lambda *a, **k: AnswerMaterial([], [], {}, 0))
    with app.app_context():
        snapshot = {k: v for k, v in published_snapshot().items() if k not in {"robot_persona", "robot_interaction"}}
        for robot in (False, True):
            with prompt_scope(snapshot):
                result = workflow.answer_question("你好", robot_base, {}, robot=robot)
            assert result["status"] == "NO_EVIDENCE"


def test_robot_endpoint_persists_chat_history_and_isolates_new_conversations(app, client, robot_base, monkeypatch):
    histories = []
    def complete(prompt, material, **kwargs):
        histories.append(deepcopy(material["history"]))
        answer = "很高兴认识你，小林！我是小维。" if material["question"] == "我叫小林" else (
            "你叫小林呀。" if material["history"].get("turns") else "小维还不知道你的名字呢。")
        return {"kind": "chat", "answer": answer}, "test"
    monkeypatch.setattr(robot_interaction, "complete_json", complete)
    first = client.post('/api/v1/robot/query', json={"serial_no": "xiaowei-test", "question": "我叫小林", "request_id": "chat-first"})
    assert first.status_code == 200 and first.json["data"]["answer_kind"] == "chat"
    cid = first.json["data"]["conversation_id"]
    followup = client.post('/api/v1/robot/conversations/query',
        headers={"X-Robot-Serial": "xiaowei-test"}, json={"question": "我叫什么", "request_id": "chat-followup", "conversation_id": cid})
    assert followup.status_code == 200, followup.json
    assert "小林" in followup.json["data"]["answer"]
    fresh = client.post('/api/v1/robot/query', json={"serial_no": "xiaowei-test", "question": "我叫什么", "request_id": "chat-new"})
    assert fresh.status_code == 200 and "还不知道" in fresh.json["data"]["answer"]
    assert histories[1]["turns"][0]["answer_kind"] == "chat" and histories[2]["turns"] == []
    with app.app_context():
        row = db.session.get(QALog, UUID(first.json["data"]["turn_id"]))
        assert row.answer_kind == "chat" and row.sources == []


def test_evaluation_uses_selected_interaction_prompt_and_reports_routing(app, client, admin, dataset, monkeypatch):
    did, example, payload = dataset
    history = {"turns": [{"question": "我叫小林", "answer": "你好小林，我是小维"}]}
    client.put(f'/api/v1/evaluations/examples/{example["id"]}', headers=admin, json={
        **payload, "expected_revision": 1, "inputs": {"question": "我叫什么", "robot": True, "context": history},
        "reference": {"expected_answer_kind": "chat", "reference_answer": "你叫小林。"}, "status": "enabled"})
    _, candidate = save(client, admin, key="robot_interaction")
    seen = []
    def complete(prompt, material, **kwargs):
        seen.append((get_prompt("robot_interaction"), material["history"]))
        return {"kind": "chat", "answer": "你叫小林呀。"}, "test"
    monkeypatch.setattr(robot_interaction, "complete_json", complete)
    run = client.post('/api/v1/evaluations/runs', headers=admin, json={
        "dataset_id": did, "name": "交流版本对比", "overrides": {"robot_interaction": candidate["id"]}}).json["data"]
    assert evaluation_worker.process_one(app)
    final = client.get(f'/api/v1/evaluations/runs/{run["id"]}', headers=admin).json["data"]
    assert final["status"] == "COMPLETED", final["error_message"]
    assert seen[0][0] != seen[1][0] and seen[1][0] == candidate["content"]
    assert all(context == history for _, context in seen)
    for arm in ("baseline", "candidate"):
        assert final["results"][0][arm]["outputs"]["answer_kind"] == "chat"
        assert final["results"][0][arm]["scores"]["answer_kind_accuracy"] == 1


@pytest.mark.parametrize("key", ["answer_robot", "robot_interaction"])
def test_chat_or_routing_failure_cannot_publish_untested_prompts(app, client, admin, dataset, monkeypatch, key):
    from app.application.prompts.release import release_reasons
    from app.entities import PromptVersion
    did, example, payload = dataset
    client.put(f'/api/v1/evaluations/examples/{example["id"]}', headers=admin, json={
        **payload, "expected_revision": 1, "inputs": {"question": "你好", "robot": True}, "status": "enabled"})
    _, candidate = save(client, admin, key=key)
    def complete(*args, **kwargs):
        if key == "robot_interaction":
            raise ChatError("分流服务不可用")
        return {"kind": "chat", "answer": "你好，我是小维。"}, "test"
    monkeypatch.setattr(robot_interaction, "complete_json", complete)
    monkeypatch.setattr(workflow, "retrieve_for_answer", lambda *a, **k: AnswerMaterial([], [], {}, 0))
    run = client.post('/api/v1/evaluations/runs', headers=admin, json={"dataset_id": did, "name": "只测问候",
        "overrides": {key: candidate["id"]}}).json["data"]
    assert evaluation_worker.process_one(app)
    client.post(f'/api/v1/evaluations/runs/{run["id"]}/reviews/{example["id"]}', headers=admin, json={"candidate": 1})
    with app.app_context():
        reasons = release_reasons(db.session.get(PromptVersion, UUID(candidate["id"])),
                                 db.session.get(EvaluationRun, UUID(run["id"])), published_snapshot())
    assert any(("未实际执行此提示词" if key == "answer_robot" else "异常回退") in reason for reason in reasons)


def test_mixed_chat_and_summary_dataset_can_release_an_executed_summary_prompt(app, client, admin, dataset, monkeypatch):
    did, example, payload = dataset
    response = client.put(f'/api/v1/evaluations/examples/{example["id"]}', headers=admin, json={
        **payload, "expected_revision": 1, "inputs": {"question": "你好", "robot": True},
        "reference": {"expected_answer_kind": "chat"}, "status": "enabled"})
    assert response.status_code == 200, response.json
    response = client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin, json={
        "name": "记住用户姓名", "status": "enabled", "inputs": {"task": "summary", "question": "整理会话摘要",
            "context": {"turns": [{"question": "我叫小林", "answer": "你好，小林！"}]}},
        "reference": {"reference_answer": "用户叫小林。"}})
    assert response.status_code == 201, response.json
    summary_id = response.json["data"]["id"]
    _, candidate = save(client, admin, key="summarize")
    monkeypatch.setattr(robot_interaction, "complete_json", lambda *a, **k: (
        {"kind": "chat", "answer": "你好，我是小维。"}, "test"))
    monkeypatch.setattr(memory, "complete_json", lambda *a, **k: ({"summary": "用户叫小林。"}, "test"))
    response = client.post('/api/v1/evaluations/runs', headers=admin, json={
        "dataset_id": did, "name": "闲聊与摘要混合验收", "overrides": {"summarize": candidate["id"]}})
    assert response.status_code == 202, response.json
    run = response.json["data"]
    assert evaluation_worker.process_one(app)
    for example_id in (example["id"], summary_id):
        response = client.post(f'/api/v1/evaluations/runs/{run["id"]}/reviews/{example_id}',
                               headers=admin, json={"candidate": 1})
        assert response.status_code == 200, response.json
    check = client.get(f'/api/v1/prompts/summarize/versions/{candidate["version"]}/release-check', headers=admin)
    assert check.status_code == 200, check.json
    assert check.json["data"]["eligible"], check.json["data"]["reasons"]
