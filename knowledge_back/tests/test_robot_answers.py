"""Robot responses stay JSON while exposing only the answer's plain text."""

from unittest.mock import Mock
from uuid import UUID

import pytest
import test_qa as qa_tests

from app.answer_text import answer_text
from app.application.conversations import memory
from app.chat import ChatError
from app.extensions import db
from app.models import QALog, Robot
from app.processors.answer_text import robot_answer_text
from app.workers import qa_worker

qa_setup = qa_tests.qa_setup


def test_plain_text_preserves_code_indices_and_table_content():
    answer = (
        "## **操作说明**\n\n"
        "访问[使用指南](https://example.com/help)，读取 `items[1]`，保留 file_name。\n\n"
        "[1] [2]\n\n"
        "```python\nvalue = items[1] * 2\nprint('**原样内容**')\n[1]\n```\n\n"
        "| 参数 | 数值 |\n| --- | --- |\n| delay_ms | 200 |\n\n"
        "[2]"
    )
    text = answer_text(answer, [{"source_id": "1"}, {"source_id": "2"}])
    assert text.startswith("操作说明")
    assert "访问使用指南，读取 items[1]，保留 file_name。" in text
    assert "value = items[1] * 2\nprint('**原样内容**')\n[1]" in text
    assert "参数\t数值" in text and "delay_ms\t200" in text
    assert text.count("[1]") == 3 and "[2]" not in text
    assert "```" not in text and "##" not in text and "| --- |" not in text


def test_robot_text_is_one_paragraph_and_preserves_conditions_numbers_and_operators():
    text = robot_answer_text(
        "先等待 **200 ms**，不要断电。\n\n[1]\n\n"
        "再读取 `items[1]`，计算 `x*y*z`，电压至少 5 V。\n\n[1]",
        [{"source_id": "1"}],
    )
    assert text == "先等待 200 ms，不要断电。 再读取 items[1]，计算 x*y*z，电压至少 5 V。"


def test_robot_legacy_formatting_has_no_table_or_list_layout():
    text = robot_answer_text(
        "## 参数\n\n| 名称 | 值 |\n| --- | --- |\n| 电压 | 5 V |\n\n"
        "1. 先接电。\n2. 再启动。\n\n[1]",
        [{"source_id": "1"}],
    )
    assert all(marker not in text for marker in ("\n", "\t", "|", "#", "1、", "2、", "[1]"))
    assert "电压 5 V" in text and "先接电。 再启动。" in text


@pytest.fixture
def robot_request(app, qa_setup):
    with app.app_context():
        robot = Robot(
            serial_no="plain-answer-robot",
            name="测试机器人",
            status="active",
            knowledge_base_id=UUID(qa_setup["base_id"]),
            binding_version=1,
        )
        db.session.add(robot)
        db.session.commit()
    return {
        "serial_no": "plain-answer-robot",
        "question": qa_tests.QUESTIONS[0],
        "request_id": "robot-plain-answer",
    }


def test_robot_json_answer_and_retry_omit_citations(
    app, client, qa_setup, robot_request, monkeypatch
):
    def completion(_prompt, material, **_options):
        if "draft" in material:
            return qa_tests.grounded_answer(_prompt, material, **_options)
        return {
            "answerable": True,
            "blocks": [
                {
                    "text": "**安装设备前**，请检查电源和接地。",
                    "evidence_ids": [material["sources"][0]["passages"][0]["id"]],
                }
            ],
        }, "test-chat"

    qa_setup["completion"].side_effect = completion
    web = qa_tests.ask(client, qa_setup)
    assert web.status_code == 200
    assert web.get_json()["data"]["sources"]
    assert "[1]" in web.get_json()["data"]["answer"]
    assert "**安装设备前**" in web.get_json()["data"]["answer"]

    web_turn = client.post(
        "/api/v1/web/conversations",
        headers=qa_setup["headers"],
        json={
            "knowledge_base_id": qa_setup["base_id"],
            "question": qa_tests.QUESTIONS[0],
            "request_id": "web-conversation-format",
        },
    )
    assert web_turn.status_code == 202
    assert qa_worker.process_one(app)
    receipt = web_turn.json["data"]
    web_result = client.get(
        f"/api/v1/web/conversations/{receipt['conversation_id']}/turns/{receipt['turn_id']}",
        headers=qa_setup["headers"],
    )
    assert "**安装设备前**" in web_result.json["data"]["answer"]

    # Robot output must not build preview URLs or rich citation HTML.
    previews = Mock(side_effect=AssertionError("Robot response must not render citations"))
    monkeypatch.setattr(qa_tests.retrieval_module, "with_preview_urls", previews)
    response = client.post("/api/v1/robot/query", json=robot_request)
    assert response.status_code == 200 and response.is_json
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"code", "message", "request_id", "data"}
    assert payload["code"] == 0
    assert payload["data"]["answer"] == "安装设备前，请检查电源和接地。"
    assert payload["data"]["sources"] == []
    prompts = [
        call.args[0]
        for call in qa_setup["completion"].call_args_list
        if "draft" not in call.args[1]
    ]
    assert prompts == [
        qa_tests.grounding_module.ANSWER_PROMPT,
        qa_tests.grounding_module.ANSWER_PROMPT,
        qa_tests.grounding_module.ROBOT_ANSWER_PROMPT,
    ]
    calls = qa_setup["completion"].call_count
    replay = client.post("/api/v1/robot/query", json=robot_request)
    assert replay.status_code == 200 and replay.get_json()["data"] == payload["data"]
    assert qa_setup["completion"].call_count == calls
    previews.assert_not_called()
    with app.app_context():
        log = db.session.scalar(
            db.select(QALog).where(QALog.request_id == robot_request["request_id"])
        )
        assert log.source_type == "ROBOT" and log.sources
        assert "[1]" in log.answer


def test_robot_followup_and_failed_retry_use_plain_answer_with_context(
    app, client, qa_setup, robot_request, monkeypatch
):
    def completion(prompt, material, **options):
        if "draft" in material:
            return qa_tests.grounded_answer(prompt, material, **options)
        assert prompt == qa_tests.grounding_module.ROBOT_ANSWER_PROMPT
        texts = (
            ("**状态灯亮起后**即可开始操作。",)
            if material["question"] == "然后呢？"
            else ("先检查**电源和接地**。", "确认连接线完好后接通电源。")
        )
        return {
            "blocks": [
                {"text": text, "evidence_ids": [material["sources"][0]["passages"][0]["id"]]}
                for text in texts
            ]
        }, "test-chat"

    qa_setup["completion"].side_effect = completion
    first = client.post("/api/v1/robot/query", json=robot_request).json["data"]
    assert first["status"] == "SUCCESS"
    assert first["answer"] == "先检查电源和接地。 确认连接线完好后接通电源。"

    def resolve(prompt, material, **options):
        assert "机器人澄清只用一句简短的纯文本问题" in prompt
        assert material["history"]["turns"][0]["question"] == robot_request["question"]
        return {"resolved_question": "安装设备后何时可以操作？", "clarification": None}, "test"

    monkeypatch.setattr(memory, "complete_json", resolve)
    qa_setup["completion"].side_effect = ChatError("问答暂时不可用")
    failed = client.post(
        "/api/v1/robot/conversations/query",
        json={
            **robot_request,
            "question": "然后呢？",
            "conversation_id": first["conversation_id"],
            "request_id": "robot-followup-format",
        },
    ).json["data"]
    assert failed["status"] == "FAILED"
    assert failed["conversation_id"] == first["conversation_id"]

    qa_setup["completion"].side_effect = completion
    retried = client.post(
        f"/api/v1/robot/conversations/{failed['conversation_id']}/turns/{failed['turn_id']}/retry",
        headers={"X-Robot-Serial": robot_request["serial_no"]},
        json={},
    )
    assert retried.status_code == 200
    assert retried.json["data"]["status"] == "SUCCESS"
    assert retried.json["data"]["answer"] == "状态灯亮起后即可开始操作。"
    assert retried.json["data"]["sources"] == []
    assert retried.json["data"]["turn_no"] == 2
    assert retried.json["data"]["turn_id"] == failed["turn_id"]


@pytest.mark.parametrize(
    ("status", "answer"),
    [
        ("NO_EVIDENCE", "当前资料不足，暂时无法回答。"),
        ("SOURCES_ONLY", "暂时无法整理出可靠回答，请换个问法。"),
    ],
)
def test_robot_without_answer_does_not_refer_to_missing_sources(
    app, client, qa_setup, robot_request, status, answer, monkeypatch
):
    monkeypatch.setattr(
        qa_worker,
        "answer_question",
        lambda *args, **kwargs: {
            "status": status,
            "answer": "已为你列出相关资料，请查看原文。",
            "sources": [],
        },
    )
    response = client.post("/api/v1/robot/query", json=robot_request)
    assert response.status_code == 200
    assert response.json["data"]["status"] == status
    assert response.get_json()["data"]["answer"] == answer
    qa_setup["completion"].assert_not_called()


def test_unregistered_robot_still_returns_json_error(client):
    response = client.post("/api/v1/robot/query", json={"serial_no": "unregistered"})
    assert response.status_code == 403 and response.is_json
    assert response.get_json()["code"] == 43001
    assert response.get_json()["data"] is None
