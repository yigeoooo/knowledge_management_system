import pytest

from app.application.prompts.composition import compile_prompt, encode_sections


def test_channel_and_evidence_isolation():
    content = encode_sections({"common": "事实", "web": "表格", "robot": "纯文本",
                                   "knowledge": "文档", "realtime": "时效"})
    web = compile_prompt(content, channel="web", evidence=("knowledge",))
    robot = compile_prompt(content, channel="robot", evidence=("realtime", "knowledge"))
    assert web.content == "事实\n\n表格\n\n文档"
    assert robot.content == "事实\n\n纯文本\n\n文档\n\n时效"
    assert robot.sections == ("common", "robot", "knowledge", "realtime")
    assert web.sha256 != robot.sha256
    assert robot == compile_prompt(content, channel="robot", evidence=("knowledge", "realtime"))


@pytest.mark.parametrize("text", ["旧规则\n保留空格  ", '{"answer":"示例"}', "普通 {JSON} 示例"])
def test_legacy_text_preserved(text):
    result = compile_prompt(text, channel="robot")
    assert result.content == text
    assert result.sections == ()
    assert result.composer_version == "legacy-text-v1"


@pytest.mark.parametrize("sections", [{}, {"common":" "}, {"common":"ok", "unknown":"bad"},
                                      {"common":"ok", "robot":3}])
def test_invalid_sections(sections):
    with pytest.raises(ValueError):
        encode_sections(sections)


def test_web_tools_rejected():
    with pytest.raises(ValueError):
        compile_prompt("legacy", channel="web", evidence=("realtime",))


def test_unknown_format_rejected():
    with pytest.raises(ValueError):
        compile_prompt('{"format":"v99","sections":{}}', channel="robot")
