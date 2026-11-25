"""One understanding call per robot turn; channel permissions are server-owned."""
from ...core.extensions import db
from ...entities import KnowledgeBase
from ...integrations.ai.chat_adapter import ChatFormatError, complete_json
from ...integrations.ai.schemas import ConversationPlan
from ...processors.answer_text import robot_answer_text
from ..prompts.registry import effective_prompt
from ..realtime.service import capabilities


def plan(question, context, base_id, *, robot, runtime, fixture=False):
    if not robot and not context.get("turns") and not context.get("summary"):
        return {"kind": "knowledge", "resolved_question": question, "knowledge_query": question,
                "tool_requests": [], "unavailable": [], "answer": None, "model": None}
    base = db.session.get(KnowledgeBase, base_id)
    scope = {"name": base.name, "description": (base.description or "")[:2000]} if base else {}
    db.session.rollback()
    available = capabilities(fixture) if robot else {"tools": []}
    payload, model = complete_json(
        effective_prompt("conversation_plan", robot=robot, evidence=("knowledge", "realtime") if robot else ("knowledge",)),
        {"question": question, "history": context, "knowledge_base_scope": scope,
         "channel": "robot" if robot else "web", "runtime": runtime,
         "tool_capabilities": available}, schema=ConversationPlan, max_tokens=1500, timeout_seconds=35)
    decision = ConversationPlan.model_validate(payload)
    direct = decision.intent in {"chat", "general", "clarification"}
    if (not robot and decision.intent not in {"knowledge", "clarification"}) or (
        decision.intent != "realtime" and (decision.tool_requests or decision.unavailable)
    ) or (direct and (not decision.direct_answer or decision.knowledge_query)) or (
        not direct and decision.direct_answer
    ) or (decision.intent == "realtime" and not decision.tool_requests and not decision.unavailable):
        raise ChatFormatError("调度结果与渠道或意图约束不一致")
    if any(t.name not in available["tools"] for t in decision.tool_requests):
        raise ChatFormatError("调度请求了未启用的工具")
    if decision.intent == "knowledge" and not decision.knowledge_query:
        raise ChatFormatError("知识问答缺少检索问题")
    answer = robot_answer_text(decision.direct_answer, []) if robot and direct else decision.direct_answer
    return {"kind": decision.intent, "resolved_question": decision.resolved_question,
            "answer": answer, "model": model, "knowledge_query": decision.knowledge_query,
            "tool_requests": [t.model_dump() for t in decision.tool_requests], "unavailable": decision.unavailable}
