"""Robot responses stay JSON while exposing only the answer's plain text."""

from unittest.mock import Mock
from uuid import UUID

import pytest
import test_qa as qa_tests

from app.answer_text import answer_text
from app.extensions import db
from app.models import QALog, Robot

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


@pytest.fixture
def robot_request(app):
    with app.app_context():
        robot = Robot(serial_no="plain-answer-robot", name="测试机器人", status="active")
        db.session.add(robot)
        db.session.commit()
    return {
        "serial_no": "plain-answer-robot",
        "knowledge_base_code": "qa-fixture",
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

    # Robot output must not build preview URLs or rich citation HTML.
    previews = Mock(side_effect=AssertionError("Robot response must not render citations"))
    monkeypatch.setattr(qa_tests.qa_module, "with_preview_urls", previews)
    response = client.post("/api/v1/robot/query", json=robot_request)
    assert response.status_code == 200 and response.is_json
    payload = response.get_json()
    assert set(payload) == {"code", "message", "request_id", "data"}
    assert payload["code"] == 0
    assert payload["data"] == {"answer": "安装设备前，请检查电源和接地。"}
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


@pytest.mark.parametrize("status", ["NO_EVIDENCE", "SOURCES_ONLY"])
def test_robot_without_answer_does_not_refer_to_missing_sources(
    app, client, qa_setup, robot_request, status
):
    with app.app_context():
        robot = db.session.scalar(
            db.select(Robot).where(Robot.serial_no == robot_request["serial_no"])
        )
        db.session.add(
            QALog(
                request_id=robot_request["request_id"],
                source_type="ROBOT",
                robot_id=robot.id,
                knowledge_base_id=UUID(qa_setup["base_id"]),
                question=robot_request["question"],
                status=status,
                answer="已为你列出相关资料，请查看原文。",
                sources=[],
            )
        )
        db.session.commit()
    response = client.post("/api/v1/robot/query", json=robot_request)
    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "answer": "当前知识库资料不足以给出可靠回答，请补充具体问题或相关资料。"
    }
    qa_setup["completion"].assert_not_called()


def test_unregistered_robot_still_returns_json_error(client):
    response = client.post("/api/v1/robot/query", json={"serial_no": "unregistered"})
    assert response.status_code == 403 and response.is_json
    assert response.get_json()["code"] == 43001
    assert response.get_json()["data"] is None
