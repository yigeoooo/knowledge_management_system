"""Compile candidate prompt sections without reinterpreting legacy text."""
import json
from dataclasses import dataclass
from hashlib import sha256

FORMAT = "kbs-prompt-sections-v1"
SECTIONS = ("common", "web", "robot", "knowledge", "realtime")


@dataclass(frozen=True)
class CompiledPrompt:
    content: str
    sections: tuple[str, ...]
    sha256: str
    composer_version: str


def _validate(sections):
    if not isinstance(sections, dict) or set(sections) - set(SECTIONS):
        raise ValueError("提示词包含未知分区")
    if not isinstance(sections.get("common"), str) or not sections["common"].strip():
        raise ValueError("公共规则不能为空")
    if any(not isinstance(value, str) for value in sections.values()):
        raise ValueError("提示词分区必须是文本")


def encode_sections(sections: dict[str, str]) -> str:
    _validate(sections)
    return json.dumps({"format": FORMAT, "sections": sections}, ensure_ascii=False, sort_keys=True)


def compile_prompt(content: str, *, channel: str, evidence: tuple[str, ...] = ()) -> CompiledPrompt:
    if channel not in {"web", "robot"} or set(evidence) - {"knowledge", "realtime"}:
        raise ValueError("未知渠道或证据类型")
    if channel == "web" and "realtime" in evidence:
        raise ValueError("网页知识问答不支持实时工具")
    try:
        payload = json.loads(content)
    except ValueError:
        payload = None
    structured = isinstance(payload, dict) and "format" in payload
    if structured:
        if payload.get("format") != FORMAT or set(payload) != {"format", "sections"}:
            raise ValueError("不支持的提示词分区协议")
        rules = payload["sections"]
        _validate(rules)
        requested = {"common", channel, *evidence}
        selected = tuple(k for k in SECTIONS if k in requested and rules.get(k, "").strip())
        content = "\n\n".join(rules[k] for k in selected)
    else:
        selected = ()
    return CompiledPrompt(content, selected, sha256(content.encode()).hexdigest(),
                          "sections-v1" if structured else "legacy-text-v1")
