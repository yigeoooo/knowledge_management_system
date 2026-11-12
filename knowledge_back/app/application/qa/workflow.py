"""A fixed LangGraph workflow; business persistence stays outside the graph."""

from typing import Any, TypedDict

from flask import current_app
from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from ...core.extensions import db
from ...integrations.ai.langchain_adapters import KnowledgeBaseRetriever, document_source
from ...integrations.ai.langsmith_config import tracing_scope
from ...integrations.ai.langsmith_reader import destination
from ..conversations.memory import resolve_question
from ..prompts.registry import prompt_fingerprint, prompt_metadata, with_prompts
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


def understand(state):
    return resolve_question(state["question"], state["context"], robot=state.get("robot", False))


def retrieve(state):
    from ...api.retrieval.controller import search_sources

    retriever = KnowledgeBaseRetriever(
        knowledge_base_id=state["knowledge_base_id"], anchor_id=state.get("anchor"),
        material_fn=retrieve_for_answer, search_fn=search_sources,
    )
    documents = retriever.invoke(state["resolved_question"], config={"run_name": "knowledge_retriever"})
    sources = [document_source(d) for d in documents]
    material = AnswerMaterial(
        [s for s in sources if s.get("modality", "text") == "text"],
        [s for s in sources if s.get("modality") in {"image", "video"}],
        retriever.scope, retriever.retrieval_count,
    )
    db.session.rollback()
    return {"material": material, "documents": documents}


def grounded_answer(state):
    material = state["material"]
    robot = state.get("robot", False)
    answer = ROBOT_NO_EVIDENCE if robot else NO_EVIDENCE
    sources, model, status = [], None, "NO_EVIDENCE"
    if material.context:
        answer, sources, model, status = generate_answer(
            state["question"],
            material.context,
            scope={
                **material.scope,
                "resolved_question": state["resolved_question"],
                "conversation_context": state["context"],
            },
            robot=robot,
        )
    elif material.media and not robot:
        answer = "找到了相关图片或视频，但文字资料不足，请查看相关来源。"
    if material.scope.get("coverage") == "sampled_sections" and status in {"SUCCESS", "PARTIAL"}:
        if robot:
            answer = "根据目前找到的部分资料，" + answer
        else:
            answer += f"\n\n以上基于 {material.scope['covered_documents']} 篇资料的代表章节整理。"
    return {
        "result": {
            "answer": answer,
            "sources": sources + material.media,
            "model_name": model,
            "status": status,
            "retrieval_count": material.retrieval_count,
            "answer_kind": "knowledge",
            "resolved_question": state["resolved_question"],
        }
    }


def clarify(state):
    return {
        "result": {
            "answer": state["clarification"],
            "sources": [],
            "model_name": None,
            "status": "SUCCESS",
            "retrieval_count": 0,
            "answer_kind": "clarification",
            "resolved_question": state["resolved_question"],
        }
    }


def build_workflow():
    graph = StateGraph(AnswerState)
    graph.add_node("understand", understand)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grounded_answer", grounded_answer)
    graph.add_node("clarify", clarify)
    graph.add_edge(START, "understand")
    graph.add_conditional_edges(
        "understand", lambda s: "clarify" if s.get("clarification") else "retrieve"
    )
    graph.add_edge("retrieve", "grounded_answer")
    graph.add_edge("grounded_answer", END)
    graph.add_edge("clarify", END)
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
):
    from uuid import uuid4
    metadata = {key: str(value) for key, value in (trace_context or {}).items()
                if value is not None and key in {"conversation_id", "turn_id", "knowledge_base_id", "evaluation_run_id", "evaluation_example_id", "evaluation_arm"}}
    if metadata.get("conversation_id"):
        metadata["session_id"] = metadata["conversation_id"]
    metadata["prompt_versions"] = prompt_metadata()
    run_id = uuid4()
    recorder = RunRecorder()
    def diagnostic(state=None):
        material = (state or {}).get("material")
        return {
            "run_id": str(run_id), "pipeline_version": "rag-v2",
            "prompt_version": prompt_fingerprint(), "prompts": prompt_metadata(), "steps": recorder.steps,
            "token_usage": recorder.usage,
            "destination": destination(current_app.config),
                "content_captured": current_app.config.get("LANGSMITH_CAPTURE_CONTENT", False),
            "retrieval": material.scope.get("retrieval", {}) if material else {},
        }

    try:
        with tracing_scope():
            state = workflow.invoke(
                {"question": question, "knowledge_base_id": base_id, "context": context,
                 "anchor": anchor, "robot": robot},
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
