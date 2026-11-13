"""A fixed LangGraph workflow; business persistence stays outside the graph."""

from typing import Any, TypedDict

from flask import current_app
from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from ...core.extensions import db
from ...integrations.ai.langchain_adapters import KnowledgeBaseRetriever, document_source
from ...integrations.ai.langsmith_config import tracing_scope
from ...integrations.ai.langsmith_reader import destination
from ..prompts.registry import (
    prompt_fingerprint,
    prompt_metadata,
    track_prompt_usage,
    with_prompts,
)
from .grounding_service import NO_EVIDENCE, ROBOT_NO_EVIDENCE, generate_answer
from .observability import RunRecorder
from .retrieval_service import AnswerMaterial, retrieve_for_answer


class AnswerState(TypedDict, total=False):
    question: str
    knowledge_base_id: Any
    context: dict
    anchor: str | None
    robot: bool
    resolved_question: str
    clarification: str | None
    documents: list[Document]
    material: Any
    result: dict
    interaction: dict
    runtime: dict
    fixtures: list | None
    tools: list



def direct_answer(state):
    interaction = state["interaction"]
    return {"result": {"answer": interaction["answer"], "sources": [],
                       "model_name": interaction["model"], "status": "SUCCESS", "retrieval_count": 0,
                       "answer_kind": interaction["kind"], "resolved_question": state["question"]}}



def retrieve(state):
    from ...api.retrieval.controller import search_sources

    retriever = KnowledgeBaseRetriever(
        knowledge_base_id=state["knowledge_base_id"], anchor_id=state.get("anchor"),
        material_fn=retrieve_for_answer, search_fn=search_sources,
    )
    documents = retriever.invoke(state.get("interaction", {}).get("knowledge_query") or state["resolved_question"], config={"run_name": "knowledge_retriever"})
    sources = [document_source(d) for d in documents]
    material = AnswerMaterial(
        [s for s in sources if s.get("modality", "text") == "text"],
        [s for s in sources if s.get("modality") in {"image", "video"}],
        retriever.scope, retriever.retrieval_count,
    )
    db.session.rollback()
    return {"material": material, "documents": documents}



def plan_conversation(state):
    from .planning import plan
    interaction = plan(state["question"], state["context"], state["knowledge_base_id"],
                       robot=state.get("robot", False), runtime=state["runtime"],
                       fixture=state.get("fixtures") is not None)
    return {"interaction": interaction, "resolved_question": interaction["resolved_question"]}


def execute_tools(state):
    from ..realtime.service import execute
    tools = execute(state["interaction"]["tool_requests"], state["runtime"], fixtures=state.get("fixtures"))
    return {"tools": tools}


def candidate_answer(state):
    import json

    from ..realtime.service import MESSAGES
    interaction = state["interaction"]
    material = state.get("material")
    context = list(material.context) if material else []
    evidence = ["knowledge"] if context else []
    tools = state.get("tools", [])
    good = [t for t in tools if t["status"] == "success"]
    if good:
        evidence.append("realtime")
        context.extend({"source_id": f"tool-{i}", "content": json.dumps(t, ensure_ascii=False),
                        "document_title": "实时工具证据", "heading_path": t["tool"]}
                       for i, t in enumerate(good, 1))
    reasons = interaction["unavailable"] + [t.get("reason", "unavailable") for t in tools if t["status"] != "success"]
    answer, sources, model, status = ROBOT_NO_EVIDENCE if state.get("robot") else NO_EVIDENCE, [], None, "NO_EVIDENCE"
    if context:
        answer, sources, model, status = generate_answer(
            state["question"], context, robot=state.get("robot", False),
            scope={**(material.scope if material else {}), "resolved_question": state["resolved_question"], "conversation_context": state["context"],
                   "evidence_types": evidence, "runtime": state["runtime"], "robot": state.get("robot", False),
                   "unavailable": reasons})
    if material and material.media and not context and not state.get("robot"):
        answer = "找到了相关图片或视频，但文字资料不足，请查看相关来源。"
    if material and material.scope.get("coverage") == "sampled_sections" and status in {"SUCCESS", "PARTIAL"}:
        answer = "根据目前找到的部分资料，" + answer if state.get("robot") else answer + "\n\n以上基于目前找到的部分资料整理。"
    if state.get("robot"):
        from ...processors.answer_text import robot_answer_text
        answer = robot_answer_text(answer, sources)
    if not context and state.get("robot"):
        from ..robots.identity import fallback_text
        answer = fallback_text(answer)
    if reasons:
        notice = "".join(dict.fromkeys(MESSAGES.get(r, MESSAGES["unavailable"]) for r in reasons))
        answer = (answer + " " if context else "") + notice
        status = "PARTIAL" if status in {"SUCCESS", "PARTIAL"} else "NO_EVIDENCE"
    return {"result": {"answer": answer, "sources": [s for s in sources if not str(s.get("source_id", "")).startswith("tool-") and s.get("document_id")] + (material.media if material and not state.get("robot") else []),
                       "model_name": model, "status": status,
                       "retrieval_count": material.retrieval_count if material else 0,
                       "answer_kind": interaction["kind"], "resolved_question": state["resolved_question"]}}


def build_workflow():
    graph = StateGraph(AnswerState)
    graph.add_node("plan_conversation", plan_conversation)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("candidate_answer", candidate_answer)
    graph.add_conditional_edges("plan_conversation", lambda s: "direct_answer" if s["interaction"]["kind"] in {"chat", "general", "clarification"} else "execute_tools" if s["interaction"]["kind"] == "realtime" else "retrieve")
    graph.add_conditional_edges("execute_tools", lambda s: "retrieve" if s["interaction"].get("knowledge_query") else "candidate_answer")
    graph.add_edge("candidate_answer", END)
    graph.add_node("retrieve", retrieve)
    graph.add_node("direct_answer", direct_answer)
    graph.add_edge(START, "plan_conversation")
    graph.add_edge("direct_answer", END)
    graph.add_edge("retrieve", "candidate_answer")
    return graph.compile()


workflow = build_workflow()


@with_prompts
def answer_question(
    question,
    base_id,
    context,
    anchor=None,
    *,
    robot=False,
    trace_context=None,
    runtime=None,
    fixtures=None,
):
    from uuid import uuid4

    from ..realtime.service import runtime as make_runtime
    runtime = runtime or context.get("tool_runtime") or make_runtime()
    metadata = {key: str(value) for key, value in (trace_context or {}).items()
                if value is not None and key in {"conversation_id", "turn_id", "knowledge_base_id", "evaluation_run_id", "evaluation_example_id", "evaluation_arm"}}
    if metadata.get("conversation_id"):
        metadata["session_id"] = metadata["conversation_id"]
    metadata["prompt_versions"] = prompt_metadata()
    run_id = uuid4()
    recorder = RunRecorder()
    used_prompts = set()
    def diagnostic(state=None):
        material = (state or {}).get("material")
        return {
            "run_id": str(run_id), "pipeline_version": "conversation-v3",
            "prompt_version": prompt_fingerprint(), "prompts": prompt_metadata(), "steps": recorder.steps,
            "token_usage": recorder.usage,
            "destination": destination(current_app.config),
                "content_captured": current_app.config.get("LANGSMITH_CAPTURE_CONTENT", False),
            "retrieval": material.scope.get("retrieval", {}) if material else {},
            "used_prompt_keys": sorted(used_prompts),
            "prompt_compositions": getattr(used_prompts, "compositions", []),
            "runtime": runtime,
            "tools": (state or {}).get("tools", []),
            "interaction": {k: v for k, v in (state or {}).get("interaction", {}).items()
                            if k in {"kind", "fallback", "unavailable"}},
        }

    try:
        with tracing_scope(), track_prompt_usage() as used_prompts:
            state = workflow.invoke(
                {"question": question, "knowledge_base_id": base_id, "context": context,
                 "anchor": anchor, "robot": robot, "runtime": runtime, "fixtures": fixtures},
                config={"recursion_limit": 16, "run_name": "rag.answer", "run_id": run_id,
                        "tags": ["rag-v2", "robot" if robot else "web"], "metadata": metadata,
                        "callbacks": [recorder]},
            )
    except Exception as error:
        error.execution_trace = diagnostic()
        raise
    result = state["result"]
    result["execution_trace"] = diagnostic(state)
    return result
