"""A fixed LangGraph workflow; business persistence stays outside the graph."""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ...core.extensions import db
from ..conversations.memory import resolve_question
from .grounding_service import NO_EVIDENCE, ROBOT_NO_EVIDENCE, generate_answer
from .retrieval_service import retrieve_for_answer


class AnswerState(TypedDict, total=False):
    question: str
    knowledge_base_id: Any
    context: dict
    anchor: str | None
    robot: bool
    resolved_question: str
    clarification: str | None
    material: Any
    result: dict


def understand(state):
    return resolve_question(state["question"], state["context"], robot=state.get("robot", False))


def retrieve(state):
    from ...api.retrieval.controller import search_sources

    material = retrieve_for_answer(
        state["knowledge_base_id"],
        state["resolved_question"],
        anchor_id=state.get("anchor"),
        search_sources_fn=search_sources,
    )
    db.session.rollback()
    return {"material": material}


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


def answer_question(question, base_id, context, anchor=None, *, robot=False):
    return workflow.invoke(
        {
            "question": question,
            "knowledge_base_id": base_id,
            "context": context,
            "anchor": anchor,
            "robot": robot,
        },
        config={"recursion_limit": 8},
    )["result"]
