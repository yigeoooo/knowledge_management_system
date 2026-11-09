from unittest.mock import Mock

import pytest

from app import grounding
from app.chat import ChatError, ChatFormatError


@pytest.fixture
def context():
    return [
        {
            "source_id": "1",
            "chunk_id": "fixture-chunk",
            "document_title": "设备指南",
            "content": "先连接 USB 线，再运行 `start.sh` 启动程序。原始数据集不会修改。",
        }
    ]


def review_all(material, *, supported=True, complete=True):
    return {
        "checks": [{"id": block["id"], "supported": supported} for block in material["draft"]],
        "complete": complete,
    }, "fixture"


def test_markdown_formatting_and_paraphrases_do_not_reject_supported_answer(context, monkeypatch):
    def completion(_prompt, material, **_options):
        if "draft" in material:
            assert "`start.sh`" in material["draft"][0]["evidence"][0]["text"]
            return review_all(material)
        # Old compatible output: string boolean, a paraphrased answer and a plain quote.
        return {
            "answerable": "true",
            "answer": "接好设备后执行 start.sh。",
            "citations": [
                {"source_id": "1", "evidence": "先连接 USB 线，再运行 start.sh 启动程序。"}
            ],
        }, "fixture"

    monkeypatch.setattr(grounding, "complete_json", completion)
    answer, sources, _, status = grounding.generate_answer("大概怎么使用？", context)
    assert status == "SUCCESS"
    assert "start.sh" in answer and "[1]" in answer
    assert sources == context


def test_invalid_paragraph_id_is_repaired_once(context, monkeypatch):
    calls = []

    def completion(_prompt, material, **_options):
        calls.append(material)
        if "draft" in material:
            return review_all(material)
        if len(calls) == 1:
            return {"blocks": [{"text": "连接设备。", "evidence_ids": ["99.1"]}]}, "fixture"
        assert material["correction"]
        return {"blocks": [{"text": "连接设备。", "evidence_ids": ["1.1"]}]}, "fixture"

    monkeypatch.setattr(grounding, "complete_json", completion)
    assert grounding.generate_answer("如何使用？", context)[3] == "SUCCESS"
    assert len(calls) == 3


def test_exhausted_format_repairs_return_related_sources(context, monkeypatch):
    completion = Mock(side_effect=ChatFormatError("无效 JSON"))
    monkeypatch.setattr(grounding, "complete_json", completion)
    answer, sources, _, status = grounding.generate_answer("如何使用？", context)
    assert status == "SOURCES_ONLY"
    assert "相关资料" in answer
    assert sources[0]["chunk_id"] == "fixture-chunk" and "source_id" not in sources[0]
    assert completion.call_count == 2


def test_reviewer_format_failure_repairs_reviewer_without_regenerating_draft(context, monkeypatch):
    completion = Mock(
        side_effect=[
            ({"blocks": [{"text": "连接设备。", "evidence_ids": ["1.1"]}]}, "fixture"),
            ({"checks": []}, "fixture"),
            ({"checks": [{"id": "1", "supported": True}], "complete": True}, "fixture"),
        ]
    )
    monkeypatch.setattr(grounding, "complete_json", completion)
    assert grounding.generate_answer("如何开始？", context)[3] == "SUCCESS"
    assert completion.call_count == 3
    first_review = completion.call_args_list[1].args[1]
    repaired_review = completion.call_args_list[2].args[1]
    assert first_review["draft"] == repaired_review["draft"]
    assert repaired_review["correction"]


@pytest.mark.parametrize("robot", [False, True])
def test_source_id_existence_does_not_allow_unsupported_facts(context, monkeypatch, robot):
    def completion(_prompt, material, **_options):
        if "draft" in material:
            return review_all(material, supported=False, complete=False)
        return {
            "blocks": [{"text": "设备会自动删除所有原始数据。", "evidence_ids": ["1.1"]}]
        }, "fixture"

    monkeypatch.setattr(grounding, "complete_json", completion)
    answer, _, _, status = grounding.generate_answer("原始数据会怎样？", context, robot=robot)
    assert status == "NO_EVIDENCE"
    assert "自动删除" not in answer


@pytest.mark.parametrize("robot", [False, True])
def test_partial_answer_keeps_only_supported_blocks_after_repair(context, monkeypatch, robot):
    def completion(_prompt, material, **_options):
        if "draft" in material:
            return {
                "checks": [{"id": "1", "supported": True}, {"id": "2", "supported": False}],
                "complete": False,
            }, "fixture"
        return {
            "blocks": [
                {"text": "运行 start.sh。", "evidence_ids": ["1.1"]},
                {"text": "无需校准即可获得完美精度。", "evidence_ids": ["1.1"]},
            ]
        }, "fixture"

    monkeypatch.setattr(grounding, "complete_json", completion)
    answer, _, _, status = grounding.generate_answer("流程和精度如何？", context, robot=robot)
    assert status == "PARTIAL"
    assert "start.sh" in answer and "完美精度" not in answer
    if robot:
        assert answer.endswith("其余内容暂无充分依据。")


def test_service_errors_are_not_misreported_as_no_evidence(context, monkeypatch):
    completion = Mock(side_effect=ChatError("服务连接失败"))
    monkeypatch.setattr(grounding, "complete_json", completion)
    with pytest.raises(ChatError, match="连接失败"):
        grounding.generate_answer("如何使用？", context)
    assert completion.call_count == 1


def test_large_fenced_command_is_not_split_between_passages(context):
    command = "```bash\n" + "command --argument value \\\n" * 80 + "  --finish\n```"
    context[0]["content"] = "准备操作。\n\n" + command
    _, passages = grounding._passages(context)
    assert command in [item["text"] for item in passages.values()]


@pytest.mark.parametrize(
    "draft",
    [
        "| 步骤 | 操作 |\n| --- | --- |\n| 1 | 连接 USB |",
        "## 使用步骤\n\n连接 USB。",
        "1. 连接 USB。\n2. 启动程序。",
        "```sh\nstart.sh\n```",
        "<table><tr><td>连接 USB</td></tr></table>",
        "连接 USB 线，再启动程序。" * 30,
    ],
)
def test_robot_rewrites_rich_or_long_draft_then_reviews_the_short_answer(
    context, monkeypatch, draft
):
    materials = []
    expected = "先连接 USB 线，再运行 start.sh。原始数据集不会修改。"

    def completion(prompt, material, **options):
        materials.append(material)
        if "draft" in material:
            assert material["draft"][0]["text"] == expected
            assert material["draft"][0]["evidence"][0]["text"] == context[0]["content"]
            return review_all(material)
        assert prompt == grounding.ROBOT_ANSWER_PROMPT
        text = draft if len(materials) == 1 else expected
        if len(materials) > 1:
            assert material["correction"]
        return {"blocks": [{"text": text, "evidence_ids": ["1.1"]}]}, "fixture"

    monkeypatch.setattr(grounding, "complete_json", completion)
    answer, sources, _, status = grounding.generate_answer("如何使用？", context, robot=True)
    assert status == "SUCCESS" and sources == context
    assert answer == expected + "\n\n[1]"
    assert len(materials) == 3  # Initial draft, one repair, independent evidence review.


def test_robot_never_returns_table_when_repair_still_has_a_table(context, monkeypatch):
    completion = Mock(
        return_value=(
            {"blocks": [{"text": "| 操作 |\n| --- |\n| 连接 USB |", "evidence_ids": ["1.1"]}]},
            "fixture",
        )
    )
    monkeypatch.setattr(grounding, "complete_json", completion)
    answer, _, _, status = grounding.generate_answer("如何使用？", context, robot=True)
    assert status == "SOURCES_ONLY"
    assert answer == grounding.ROBOT_FORMAT_NOTICE
    assert completion.call_count == 2
