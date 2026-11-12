"""Generate and review answers against server-owned passages, with one repair attempt."""

import logging
import re
from difflib import SequenceMatcher
from time import monotonic

from ...integrations.ai.chat_adapter import ChatFormatError, complete_json
from ...integrations.ai.schemas import AnswerDraft, Review, SuggestionReview, Suggestions
from ...processors.answer_text import robot_answer_text
from ...processors.markdown import markdown_blocks
from ..prompts.registry import bootstrap_content, get_prompt, with_prompts

logger = logging.getLogger(__name__)
NO_EVIDENCE = "当前资料不足以回答这个问题。可以补充具体主题，或查看相关资料后继续提问。"
PARTIAL_NOTICE = "以上是资料中可以确认的部分，其余内容暂未找到充分依据。"
FORMAT_NOTICE = "暂未能整理出可核实的回答，已为你列出相关资料，可以先查看原文或换一种问法。"
ROBOT_NO_EVIDENCE = "当前资料不足，暂时无法回答。"
ROBOT_FORMAT_NOTICE = "暂时无法整理出可靠回答，请换个问法。"
ANSWER_PROMPT = bootstrap_content("answer_web")
ROBOT_ANSWER_PROMPT = bootstrap_content("answer_robot")
REVIEW_PROMPT = bootstrap_content("review_answer")
SUGGEST_PROMPT = bootstrap_content("suggest_questions")
SUGGEST_REVIEW_PROMPT = bootstrap_content("review_suggestions")

def _boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def _passages(sources):
    material, by_id = [], {}
    for source in sources:
        source_id = source["source_id"]
        parts, pending = [], ""
        for content, _, _ in markdown_blocks(source["content"]):
            if pending and len(pending) + len(content) + 2 > 1400:
                parts.append(pending)
                pending = ""
            pending = pending + "\n\n" + content if pending else content
        if pending:
            parts.append(pending)
        passages = []
        for index, part in enumerate(parts, 1):
            passage_id = f"{source_id}.{index}"
            passages.append({"id": passage_id, "text": part})
            by_id[passage_id] = {
                "text": part,
                "source_id": source_id,
                "document_title": source.get("document_title", ""),
                "heading": source.get("heading_path", ""),
            }
        material.append(
            {
                "source_id": source_id,
                "title": source.get("document_title", ""),
                "heading": source.get("heading_path", ""),
                "passages": passages,
            }
        )
    return material, by_id


def _ids(item, passages):
    ids = item.get("evidence_ids")
    # Accept the previous source-level shape, but review its actual support below.
    # Free-text evidence from the model is never treated as a source of truth.
    if ids is None and "source_id" in item:
        ids = [
            key for key, value in passages.items() if value["source_id"] == str(item["source_id"])
        ]
    if isinstance(ids, str):
        ids = [ids]
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 24
        or any(not isinstance(key, str) or key not in passages for key in ids)
    ):
        raise ChatFormatError("请选择输入中存在的 evidence_ids")
    return list(dict.fromkeys(ids))


def _blocks(payload, passages):
    if _boolean(payload.get("answerable")) is False:
        return []
    blocks = payload.get("blocks")
    if blocks is None and isinstance(payload.get("answer"), str):
        citations = payload.get("citations")
        if (
            not isinstance(citations, list)
            or not citations
            or not all(isinstance(c, dict) for c in citations)
        ):
            raise ChatFormatError("回答需要附带段落引用")
        ids = list(dict.fromkeys(key for c in citations for key in _ids(c, passages)))
        blocks = [{"text": payload["answer"], "evidence_ids": ids}]
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 12:
        raise ChatFormatError("请返回包含 text 和 evidence_ids 的 blocks 数组")
    result = []
    for index, block in enumerate(blocks, 1):
        if (
            not isinstance(block, dict)
            or not isinstance(block.get("text"), str)
            or not block["text"].strip()
        ):
            raise ChatFormatError("每个回答块需要非空 text")
        result.append(
            {"id": str(index), "text": block["text"].strip(), "evidence_ids": _ids(block, passages)}
        )
    if sum(len(block["text"]) for block in result) > 18000:
        raise ChatFormatError("回答过长，请保留关键步骤并缩短回答")
    return result


def _checks(payload, expected):
    checks = payload.get("checks")
    if not isinstance(checks, list) or len(checks) != len(expected):
        raise ChatFormatError("证据审阅结果不完整")
    result = {}
    for item in checks:
        if not isinstance(item, dict):
            raise ChatFormatError("证据审阅格式不正确")
        key, supported = str(item.get("id")), _boolean(item.get("supported"))
        if key not in expected or key in result or supported is None:
            raise ChatFormatError("证据审阅编号或结论不正确")
        result[key] = supported
    return result


def _call(prompt, material, deadline, *, max_tokens=4096):
    if deadline - monotonic() < 1:
        raise ChatFormatError("本次整理的时间预算已用完")
    return complete_json(
        get_prompt({ANSWER_PROMPT: "answer_web", ROBOT_ANSWER_PROMPT: "answer_robot",
                    REVIEW_PROMPT: "review_answer", SUGGEST_PROMPT: "suggest_questions",
                    SUGGEST_REVIEW_PROMPT: "review_suggestions"}[prompt]),
        material, max_tokens=max_tokens, timeout_seconds=deadline - monotonic(),
        schema={ANSWER_PROMPT: AnswerDraft, ROBOT_ANSWER_PROMPT: AnswerDraft,
                REVIEW_PROMPT: Review, SUGGEST_PROMPT: Suggestions,
                SUGGEST_REVIEW_PROMPT: SuggestionReview}.get(prompt)
    )


def _related(context):
    return [{k: v for k, v in source.items() if k != "source_id"} for source in context]


def _render(blocks, passages, context, partial, model, *, robot=False):
    used, rendered = set(), []
    for block in blocks:
        ids = list(dict.fromkeys(passages[key]["source_id"] for key in block["evidence_ids"]))
        used.update(ids)
        rendered.append(block["text"] + "\n\n" + " ".join(f"[{key}]" for key in ids))
    if partial:
        rendered.append("其余内容暂无充分依据。" if robot else PARTIAL_NOTICE)
    return (
        "\n\n".join(rendered),
        [s for s in context if s["source_id"] in used],
        model,
        "PARTIAL" if partial else "SUCCESS",
    )


def _prepare_answer(state):
    material, passages = _passages(state["context"])
    return {"material": material, "passages": passages, "deadline": monotonic() + 150,
            "correction": "", "review_correction": "", "model": None, "supported": [],
            "reviewed": False, "blocks": [], "repairs": 1, "stage": "generate"}


def _question_input(question, scope):
    """Keep user-supplied conditions next to the question, even if rewriting omits them.

    Assistant claims remain in conversation context, never in the evidence passages.
    Generation and review consume the same question representation.
    """
    context = scope.get("conversation_context") or {}
    turns = context.get("turns") or []
    questions = [t["question"] for t in turns if isinstance(t, dict)
                 and isinstance(t.get("question"), str) and t["question"].strip()]
    summary = context.get("summary") if isinstance(context.get("summary"), str) else ""
    if not questions and not summary:
        return question
    return {
        "current_question": question,
        "resolved_question": scope.get("resolved_question") or question,
        "previous_user_questions": questions,
        "conversation_summary": summary,
    }


def _generate(state):
    try:
        payload, model = _call(
            ROBOT_ANSWER_PROMPT if state.get("robot") else ANSWER_PROMPT,
            {"question": _question_input(state["question"], state.get("scope") or {}), "scope": state.get("scope") or {},
             "sources": state["material"], "correction": state["correction"]},
            state["deadline"],
        )
        blocks = _blocks(payload, state["passages"])
        if state.get("robot") and blocks:
            try:
                texts = [robot_answer_text(b["text"], [], require_paragraphs=True) for b in blocks]
            except ValueError as error:
                raise ChatFormatError(str(error)) from error
            if any(not text for text in texts):
                raise ChatFormatError("请用简短文字直接回答问题。")
            if len(blocks) > 3 or sum(len(text) for text in texts) > 300:
                raise ChatFormatError("回答过长，请保留必要条件，改为最多 3 块、共 300 字以内。")
        return {"blocks": blocks, "model": model, "stage": "generate",
                "next": "review" if blocks else "finalize", "no_answer": not blocks}
    except ChatFormatError as error:
        return {"next": "repair", "stage": "generate", "error": str(error)}


def _review_answer(state):
    try:
        blocks, passages = state["blocks"], state["passages"]
        review, _ = _call(
            REVIEW_PROMPT,
            {"question": _question_input(state["question"], state.get("scope") or {}), "scope": state.get("scope") or {},
             "correction": state["review_correction"],
             "draft": [{"id": b["id"], "text": b["text"],
                        "evidence": [passages[key] for key in b["evidence_ids"]]} for b in blocks]},
            state["deadline"], max_tokens=1200,
        )
        checks = _checks(review, {b["id"] for b in blocks})
        verified = [b for b in blocks if checks[b["id"]]]
        accepted = len(verified) == len(blocks)
        return {"reviewed": True, "supported": verified or state["supported"],
                "complete": accepted and _boolean(review.get("complete")) is True,
                "next": "finalize" if accepted else "repair", "stage": "generate",
                "error": {"issue": "请删除或重写无依据的回答块：" +
                          ",".join(b["id"] for b in blocks if not checks[b["id"]]),
                          "previous_draft": [{"id": b["id"], "text": b["text"]} for b in blocks]}}
    except ChatFormatError as error:
        return {"next": "repair", "stage": "review", "error": str(error)}


def _repair_answer(state):
    if not state["repairs"]:
        return {"next": "finalize"}
    field = "correction" if state["stage"] == "generate" else "review_correction"
    return {"repairs": state["repairs"] - 1, field: state["error"], "next": state["stage"]}


def _finalize_answer(state):
    robot, model = state.get("robot", False), state["model"]
    if state["supported"]:
        result = _render(state["supported"], state["passages"], state["context"],
                         not state.get("complete", False), model, robot=robot)
    elif state["reviewed"] or state.get("no_answer"):
        result = (ROBOT_NO_EVIDENCE if robot else NO_EVIDENCE,
                  _related(state["context"]), model, "NO_EVIDENCE")
    else:
        result = (ROBOT_FORMAT_NOTICE if robot else FORMAT_NOTICE,
                  _related(state["context"]), model, "SOURCES_ONLY")
    return {"output": result}


def _answer_graph():
    from typing import Any, TypedDict

    from langgraph.graph import END, START, StateGraph

    class State(TypedDict, total=False):
        question: str
        context: list
        scope: dict
        robot: bool
        material: list
        passages: dict
        deadline: float
        correction: Any
        review_correction: str
        model: str | None
        supported: list
        reviewed: bool
        blocks: list
        repairs: int
        stage: str
        next: str
        error: Any
        no_answer: bool
        complete: bool
        output: tuple

    graph = StateGraph(State)
    for name, node in [("prepare", _prepare_answer), ("generate", _generate),
                       ("review", _review_answer), ("repair", _repair_answer),
                       ("finalize", _finalize_answer)]:
        graph.add_node(name, node)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "generate")
    graph.add_conditional_edges("generate", lambda s: s["next"], ["review", "repair", "finalize"])
    graph.add_conditional_edges("review", lambda s: s["next"], ["repair", "finalize"])
    graph.add_conditional_edges("repair", lambda s: s["next"], ["generate", "review", "finalize"])
    graph.add_edge("finalize", END)
    return graph.compile(name="grounded_answer")


answer_graph = _answer_graph()


@with_prompts
def generate_answer(question, context, *, scope=None, robot=False):
    from ...integrations.ai.langsmith_config import tracing_scope
    with tracing_scope():
        return answer_graph.invoke(
            {"question": question, "context": context, "scope": scope or {}, "robot": robot},
            config={"recursion_limit": 16, "run_name": "rag.grounding"},
        )["output"]


def _suggestion_candidates(payload, passages):
    items = payload.get("questions")
    if not isinstance(items, list):
        raise ChatFormatError("请返回 questions 数组")
    candidates = []
    for item in items[:9]:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        if (
            not isinstance(question, str)
            or not 6 <= len(question.strip()) <= 120
            or any(ord(c) < 32 for c in question)
        ):
            continue
        try:
            ids = _ids(item, passages)
        except ChatFormatError:
            continue
        source_ids = {passages[key]["source_id"] for key in ids}
        if len(source_ids) != 1:
            continue
        candidates.append(
            {
                "id": str(len(candidates) + 1),
                "question": question.strip(),
                "evidence_ids": ids,
                "source_id": next(iter(source_ids)),
            }
        )
    if items and not candidates:
        raise ChatFormatError("推荐问题缺少有效段落编号")
    return candidates


@with_prompts
def generate_suggestions(sources):
    material, passages = _passages(sources)
    by_source = {source["source_id"]: source for source in sources}
    deadline = monotonic() + 90
    accepted, correction, review_correction = [], "", ""
    stage, repairs, candidates = "generate", 1, []
    while True:
        try:
            if stage == "generate":
                payload, _ = _call(
                    SUGGEST_PROMPT,
                    {"sources": material, "correction": correction},
                    deadline,
                    max_tokens=1800,
                )
                candidates = _suggestion_candidates(payload, passages)
                if not candidates:
                    return accepted
                stage = "review"
            review, _ = _call(
                SUGGEST_REVIEW_PROMPT,
                {
                    "correction": review_correction,
                    "candidates": [
                        {
                            "id": item["id"],
                            "question": item["question"],
                            "evidence": [passages[key] for key in item["evidence_ids"]],
                        }
                        for item in candidates
                    ],
                },
                deadline,
                max_tokens=1000,
            )
            checks = _checks(review, {item["id"] for item in candidates})
            for item in candidates:
                if not checks[item["id"]]:
                    continue
                key = re.sub(r"\W", "", item["question"]).casefold()
                if any(
                    old["source"]["chunk_id"] == by_source[item["source_id"]]["chunk_id"]
                    or SequenceMatcher(
                        None, key, re.sub(r"\W", "", old["question"]).casefold()
                    ).ratio()
                    > 0.85
                    for old in accepted
                ):
                    continue
                accepted.append(
                    {
                        "question": item["question"],
                        "source": {
                            k: v
                            for k, v in by_source[item["source_id"]].items()
                            if k not in {"source_id", "content"}
                        },
                    }
                )
                if len(accepted) == 3:
                    return accepted
            if all(checks.values()):
                return accepted
            if not repairs:
                break
            repairs -= 1
            correction = "请只生成能从段落完整回答的简单问题，不追加效果、原因等缺乏依据的子问题。"
            stage = "generate"
        except ChatFormatError as error:
            logger.info(
                "qa_output_repair stage=suggestions_%s remaining=%s reason=%s",
                stage,
                repairs,
                str(error),
            )
            if not repairs:
                break
            repairs -= 1
            if stage == "generate":
                correction = str(error)
            else:
                review_correction = str(error)
    return accepted
