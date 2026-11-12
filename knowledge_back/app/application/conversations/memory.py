"""Bounded per-conversation memory; history is context, never knowledge evidence."""

import json

from flask import current_app

from ...core.extensions import db
from ...entities import QAConversation, QALog, now
from ...integrations.ai.chat_adapter import ChatError, ChatFormatError, complete_json
from ...integrations.ai.schemas import ResolvedQuestion, Summary
from ..prompts.registry import get_prompt
from .service import COMPLETED


def _cost(value):
    # UTF-8 bytes conservatively bound byte-pair token usage, including JSON framing.
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _clip(value, budget):
    return value.encode("utf-8")[: max(0, budget)].decode("utf-8", errors="ignore")


def _item(row):
    return {
        "turn_no": row.turn_no,
        "question": row.question,
        "answer": row.answer or "",
        "status": row.status,
        "answer_kind": row.answer_kind,
    }


def summarize_context(previous_summary, turns):
    """Shared summary operation for real conversation compaction and fixed-history evaluation."""
    payload, _ = complete_json(
        get_prompt("summarize"), {"previous_summary": previous_summary, "turns": turns},
        schema=Summary, max_tokens=2500, timeout_seconds=30,
    )
    summary = payload.get("summary")
    if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 4000:
        raise ChatFormatError("会话摘要格式不正确")
    return summary.strip()


def prepare_context(cid, before_turn, *, turn_id=None, lease_token=None):
    c = db.session.get(QAConversation, cid)
    version, through, summary = c.memory_version, c.summary_through_turn_no, c.memory_summary
    recent_count = max(1, min(current_app.config["QA_RECENT_TURNS"], 20))
    budget = max(1000, current_app.config["QA_HISTORY_BUDGET"])
    query = db.select(QALog).where(
        QALog.conversation_id == cid,
        QALog.turn_no < before_turn,
        QALog.turn_no > through,
        QALog.status.in_(COMPLETED),
    )
    # Bound database reads and model calls even when recovering a very old conversation.
    prefix = [_item(row) for row in db.session.scalars(query.order_by(QALog.turn_no).limit(64))]
    db.session.rollback()
    notice = None
    if len(prefix) > recent_count:
        older = []
        for item in prefix[:-recent_count]:
            if older and _cost(older + [item]) > 18000:
                break
            if _cost(item) > 18000:
                item = {
                    **item,
                    "answer": _clip(item["answer"], max(0, 17000 - _cost(item["question"]))),
                    "answer_truncated": True,
                }
            older.append(item)
        try:
            updated_summary = summarize_context(summary, older)
        except ChatError:
            notice = "较早对话暂未能完整整理；如追问涉及遗漏内容，请补充说明。"
        else:
            # Parent lock follows the same order as claiming, deletion and rebinding.
            current = db.session.scalar(
                db.select(QAConversation)
                .where(QAConversation.id == cid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            leased = turn_id is None or db.session.scalar(
                db.select(QALog.id).where(
                    QALog.id == turn_id,
                    QALog.lease_token == lease_token,
                    QALog.status == "PROCESSING",
                    QALog.lease_expires_at > now(),
                )
            )
            if (
                leased
                and current.memory_version == version
                and not current.deleted_at
                and not current.closed_at
            ):
                summary, through, version = (
                    updated_summary.strip(),
                    older[-1]["turn_no"],
                    version + 1,
                )
                current.memory_summary = summary
                current.summary_through_turn_no = through
                current.memory_version = version
                db.session.commit()
            else:
                db.session.rollback()
    # Fetch the newest complete turns after the saved coverage. Any gap is explicit.
    rows = db.session.scalars(
        db.select(QALog)
        .where(
            QALog.conversation_id == cid,
            QALog.turn_no > through,
            QALog.turn_no < before_turn,
            QALog.status.in_(COMPLETED),
        )
        .order_by(QALog.turn_no.desc())
        .limit(recent_count + 1)
    ).all()
    history = [_item(row) for row in reversed(rows[:recent_count])]
    if len(rows) > recent_count:
        notice = notice or "当前回答未覆盖全部较早对话，如有遗漏请补充具体内容。"
    db.session.rollback()
    context = {
        "summary": summary,
        "summary_through_turn_no": through,
        "summary_version": version,
        "turns": [],
        "through_turn_no": before_turn - 1,
        "notice": notice,
    }
    if _cost(summary) > budget // 2:
        context["summary"] = _clip(summary, budget // 2 - 2)
        context["notice"] = "较早对话摘要已缩短，如有遗漏请补充具体内容。"
    for item in reversed(history):
        candidate = {**context, "turns": [item, *context["turns"]]}
        if _cost(candidate) > budget - 256:
            context["notice"] = "当前回答未覆盖全部较早对话，如有遗漏请补充具体内容。"
            break
        context = candidate
    return context


def resolve_question(question, context, *, robot=False):
    if not context.get("turns") and not context.get("summary"):
        return {"resolved_question": question, "clarification": None}
    payload, _ = complete_json(
        get_prompt("resolve_robot" if robot else "resolve_web"),
        {"question": question, "history": context},
        timeout_seconds=35,
        schema=ResolvedQuestion,
    )
    clarification = payload.get("clarification")
    if clarification is not None:
        if not isinstance(clarification, str) or not 1 <= len(clarification.strip()) <= 500:
            raise ChatFormatError("追问澄清格式不正确")
        return {"resolved_question": question, "clarification": clarification.strip()}
    resolved = payload.get("resolved_question")
    if not isinstance(resolved, str) or not 1 <= len(resolved.strip()) <= 4000:
        raise ChatFormatError("追问理解失败，请补充具体问题后重试")
    return {"resolved_question": resolved.strip(), "clarification": None}
