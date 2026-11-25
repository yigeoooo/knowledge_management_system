import importlib
from types import SimpleNamespace
from uuid import uuid4

from app.application.conversations import memory
from app.entities import KnowledgeBase, QAConversation, QALog, User
from app.extensions import db
from app.integrations.ai.chat_adapter import ChatError

graph = importlib.import_module("app.application.qa.workflow")


def history(count, *, answer="已回答"):
    user = db.session.scalar(db.select(User))
    base = db.session.scalar(db.select(KnowledgeBase))
    c = QAConversation(
        id=uuid4(),
        source_type="WEB",
        user_id=user.id,
        knowledge_base_id=base.id,
        title="独立会话",
        creation_request_id=str(uuid4()),
        next_turn_no=count + 1,
    )
    db.session.add(c)
    db.session.flush()
    for number in range(1, count + 1):
        db.session.add(
            QALog(
                id=uuid4(),
                conversation_id=c.id,
                turn_no=number,
                source_type="WEB",
                user_id=user.id,
                knowledge_base_id=base.id,
                request_id=str(uuid4()),
                question=f"第{number}个问题",
                answer=answer,
                status="SUCCESS",
                sources=[],
            )
        )
    db.session.commit()
    return c.id


def test_summary_and_recent_turns_cover_history_without_duplication(app, monkeypatch):
    calls = []

    def summarize(system, payload, **kwargs):
        calls.append(payload)
        return {"summary": "讨论了前三个问题"}, "test"

    monkeypatch.setattr(memory, "complete_json", summarize)
    with app.app_context():
        cid = history(9)
        context = memory.prepare_context(cid, 10)
        assert [item["turn_no"] for item in calls[0]["turns"]] == [1, 2, 3]
        assert [item["turn_no"] for item in context["turns"]] == [4, 5, 6, 7, 8, 9]
        assert context["summary_through_turn_no"] == 3
        assert context["notice"] is None
        assert memory.prepare_context(cid, 10) == context
        assert len(calls) == 1
        other = history(0)
        assert memory.prepare_context(other, 1)["summary"] == ""


def test_summary_failure_preserves_recent_history_and_reports_omissions(app, monkeypatch):
    def fail(*args, **kwargs):
        raise ChatError("Unavailable")

    monkeypatch.setattr(memory, "complete_json", fail)
    with app.app_context():
        cid = history(9)
        context = memory.prepare_context(cid, 10)
        assert context["notice"]
        assert context["turns"][-1]["turn_no"] == 9
        assert db.session.get(QAConversation, cid).summary_through_turn_no == 0


def test_large_multibyte_history_is_bounded_and_stale_worker_cannot_write_summary(app, monkeypatch):
    calls = []

    def summarize(system, payload, **kwargs):
        calls.append(payload)
        return {"summary": "历史摘要"}, "test"

    monkeypatch.setattr(memory, "complete_json", summarize)
    with app.app_context():
        cid = history(100, answer="中文内容" * 300)
        context = memory.prepare_context(cid, 101, turn_id=uuid4(), lease_token=uuid4())
        assert len(calls) == 1
        assert memory._cost(calls[0]["turns"]) <= 18000
        assert memory._cost(context) <= app.config["QA_HISTORY_BUDGET"]
        assert context["notice"]
        assert db.session.get(QAConversation, cid).memory_version == 0


def test_followup_retrieves_resolved_question_and_history_cannot_replace_evidence(app, monkeypatch):
    context = {"summary": "", "turns": [{"question": "介绍蜀南竹海", "answer": "旧答案"}]}
    monkeypatch.setattr(
        memory,
        "complete_json",
        lambda *a, **k: (
            {"resolved_question": "蜀南竹海的门票价格", "clarification": None},
            "test",
        ),
    )
    queries = []

    def retrieve(base, question, **kwargs):
        queries.append(question)
        return SimpleNamespace(context=[], media=[], scope={}, retrieval_count=0)

    monkeypatch.setattr(graph, "retrieve_for_answer", retrieve)

    def forbidden(*args, **kwargs):
        raise AssertionError("没有新证据时不能用旧回答生成知识事实")

    monkeypatch.setattr(graph, "generate_answer", forbidden)
    with app.app_context():
        result = graph.answer_question("门票呢？", uuid4(), context)
    assert queries == ["蜀南竹海的门票价格"]
    assert result["status"] == "NO_EVIDENCE"
    assert result["sources"] == []


def test_ambiguous_followup_clarifies_before_retrieval(app, monkeypatch):
    monkeypatch.setattr(
        memory, "complete_json", lambda *a, **k: ({"clarification": "你指的是哪个景点？"}, "test")
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("先澄清，不应检索")

    monkeypatch.setattr(graph, "retrieve_for_answer", forbidden)
    with app.app_context():
        result = graph.answer_question("那里呢？", uuid4(), {"summary": "讨论了多个景点"})
    assert result["answer_kind"] == "clarification"
    assert result["answer"] == "你指的是哪个景点？"
