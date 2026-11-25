"""Route robot conversation without turning missing business evidence into guesses."""

from flask import current_app
from pydantic import ValidationError

from ...core.extensions import db
from ...entities import KnowledgeBase
from ...integrations.ai.chat_adapter import ChatError, ChatFormatError, complete_json
from ...integrations.ai.schemas import RobotInteraction
from ...processors.answer_text import robot_answer_text
from ..prompts.registry import robot_prompt


def classify_interaction(question, context, base_id):
    base = db.session.get(KnowledgeBase, base_id)
    scope = {"name": base.name, "description": (base.description or "")[:2000]} if base else {}
    db.session.rollback()
    try:
        payload, model = complete_json(
            robot_prompt("robot_interaction"),
            {"question": question, "history": context, "knowledge_base_scope": scope},
            schema=RobotInteraction, max_tokens=700, timeout_seconds=20,
        )
        decision = RobotInteraction.model_validate(payload)
        if decision.kind in {"chat", "general", "clarification"}:
            answer = robot_answer_text(decision.answer or "", [])
            if not answer or len(answer) > 300:
                raise ChatFormatError("机器人交流回答格式不正确")
        elif decision.kind == "realtime":
            # No live data tool exists. Never pass model-invented conditions to
            # the user, even if a provider returns an answer against the schema instructions.
            answer = (
                "小维暂时查不到实时天气，你可以看看手机上的天气预报，出门前留意一下温度和降雨哦。"
                if decision.realtime_topic == "weather"
                else "小维目前还不能查询实时信息，暂时没法确认，建议你通过相关官方渠道查看最新情况。"
            )
        else:
            answer = None
        if decision.kind == "realtime":
            from ..robots.identity import fallback_text
            answer = fallback_text(answer)
        return {"kind": decision.kind, "answer": answer, "model": model}
    except (ChatError, ValidationError) as error:
        current_app.logger.warning("robot interaction routing failed; using knowledge retrieval type=%s",
                                   type(error).__name__, exc_info=True)
        return {"kind": "knowledge", "answer": None, "model": None, "fallback": type(error).__name__}
