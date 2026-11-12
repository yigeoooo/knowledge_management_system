"""Repeatable RAG experiments. Gold labels are supplied by operators, never inferred."""
from pathlib import Path
from statistics import mean
from typing import Literal

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field

from ...core.extensions import db
from ...entities import KnowledgeBase
from ..prompts.registry import with_prompts
from .retrieval_service import retrieve_for_answer
from .workflow import answer_question


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    knowledge_base_code: str
    context: dict = Field(default_factory=dict)
    robot: bool = False
    task: Literal["answer", "summary", "suggestions"] = "answer"


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_documents: list[str] = Field(default_factory=list)
    expected_document_ids: list[str] = Field(default_factory=list, max_length=30)
    answer_points: list[str] = Field(default_factory=list)
    expected_status: str | None = None
    reference_answer: str = Field(default="", max_length=5000)
    source_notes: str = Field(default="", max_length=5000)
    forbidden_points: list[str] = Field(default_factory=list)


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    inputs: EvaluationInput
    outputs: Reference


def load_examples(path):
    records = [Example.model_validate_json(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not records:
        raise ValueError("评测集为空")
    if len({r.name for r in records}) != len(records):
        raise ValueError("评测样本名称重复")
    return records


def metrics(outputs, reference):
    by_id = bool(reference.get("expected_document_ids"))
    expected = set(reference.get("expected_document_ids" if by_id else "expected_documents") or [])
    ranked = list(dict.fromkeys(outputs.get("retrieved_document_ids" if by_id else "retrieved_documents") or []))[:10]
    result = {}
    if expected:
        hits = expected.intersection(ranked)
        result["document_recall_at_10"] = len(hits) / len(expected)
        result["document_precision_at_10"] = len(hits) / max(1, len(ranked))
        result["document_mrr"] = next((1 / i for i, title in enumerate(ranked, 1) if title in expected), 0)
    if outputs.get("mode") != "retrieval":
        if reference.get("expected_status"):
            result["status_accuracy"] = float(outputs.get("status") == reference["expected_status"])
        points = reference.get("answer_points") or []
        if points:
            result["answer_point_literal_coverage"] = sum(p in (outputs.get("answer") or "") for p in points) / len(points)
        forbidden = reference.get("forbidden_points") or []
        if forbidden:
            result["forbidden_point_absence"] = sum(p not in (outputs.get("answer") or "") for p in forbidden) / len(forbidden)
        cited = set(outputs.get("cited_document_ids" if by_id else "cited_documents") or [])
        if expected:
            result["citation_document_precision"] = len(cited.intersection(expected)) / max(1, len(cited))
    return result


@with_prompts
def evaluate_input(inputs, *, retrieval_only=False, trace_context=None):
    inputs = EvaluationInput.model_validate(inputs)
    base_id = db.session.scalar(db.select(KnowledgeBase.id).where(
        KnowledgeBase.code == inputs.knowledge_base_code, KnowledgeBase.status == "active"))
    db.session.rollback()
    if base_id is None:
        raise ValueError("评测知识库不存在或已停用")
    if retrieval_only:
        if inputs.context:
            from ..conversations.memory import resolve_question
            understood = resolve_question(inputs.question, inputs.context, robot=inputs.robot)
            if understood.get("clarification"):
                return {"mode": "retrieval", "retrieved_documents": [], "status": "CLARIFICATION"}
            question = understood["resolved_question"]
        else:
            question = inputs.question
        material = retrieve_for_answer(base_id, question)
        return {"mode": "retrieval", "retrieved_document_ids": [s["document_id"] for s in material.context], "retrieved_documents":
                [s["document_title"] for s in material.context]}
    from time import monotonic
    started = monotonic()
    if inputs.task == "answer":
        result = answer_question(inputs.question, base_id, inputs.context, robot=inputs.robot, trace_context=trace_context)
    else:
        from .observability import record_turn
        def operation(_):
            if inputs.task == "summary":
                from ..conversations.memory import summarize_context
                answer = summarize_context(inputs.context.get("summary", ""), inputs.context.get("turns", []))
                return {"answer": answer, "status": "SUCCESS", "sources": [], "retrieved_documents": []}
            from .grounding_service import generate_suggestions
            material = retrieve_for_answer(base_id, inputs.question)
            questions = generate_suggestions(material.context) if material.context else []
            return {"answer": "\n".join(q["question"] for q in questions),
                    "status": "SUCCESS" if questions else "NO_EVIDENCE",
                    "sources": [], "retrieved_documents": [s["document_title"] for s in material.context],
                    "retrieved_document_ids": [s["document_id"] for s in material.context],
                    "cited_document_ids": [q["source"]["document_id"] for q in questions],
                    "cited_documents": [q["source"]["document_title"] for q in questions]}
        result = record_turn(operation, metadata={"knowledge_base_id": base_id, **(trace_context or {})}, robot=inputs.robot)
    if inputs.robot and inputs.task == "answer":
        from ...processors.answer_text import robot_answer_text
        result["answer"] = robot_answer_text(result["answer"], result["sources"])
    trace = result["execution_trace"].get("retrieval", {})
    selected = set(trace.get("selected", []))
    # Expanded context can contain siblings absent from initial candidates.
    titles = trace.get("context_documents") or [s["document_title"] for s in trace.get("ranked", []) if s["chunk_id"] in selected]
    document_ids = trace.get("context_document_ids") or [s["document_id"] for s in trace.get("ranked", []) if s["chunk_id"] in selected]
    return {"mode": inputs.task, "answer": result["answer"], "status": "CLARIFICATION" if result.get("answer_kind") == "clarification" else result["status"],
            "retrieved_documents": result.get("retrieved_documents", titles),
            "retrieved_document_ids": result.get("retrieved_document_ids", document_ids),
            "cited_documents": result.get("cited_documents", [s["document_title"] for s in result["sources"] if s.get("source_id")]),
            "cited_document_ids": result.get("cited_document_ids", [s["document_id"] for s in result["sources"] if s.get("source_id")]),
            "run_id": result["execution_trace"]["run_id"],
            "latency_ms": int((monotonic() - started) * 1000),
            "token_usage": result["execution_trace"].get("token_usage", {}),
            "prompt_versions": result["execution_trace"].get("prompts", {})}


def run_local(examples, *, retrieval_only=False):
    rows = []
    for example in examples:
        try:
            result = evaluate_input(example.inputs.model_dump(), retrieval_only=retrieval_only)
            scores = metrics(result, example.outputs.model_dump())
            rows.append({"name": example.name, "outputs": result, "scores": scores, "error": None})
        except Exception as error:  # noqa: BLE001 - report each failed example without leaking data
            # Do not leak provider bodies or database connection strings into a report.
            rows.append({"name": example.name, "outputs": {}, "scores": {}, "error": type(error).__name__})
    keys = {key for row in rows for key in row["scores"]}
    return {"pipeline_version": "rag-v2", "examples": rows,
            "failures": sum(row["error"] is not None for row in rows),
            "metrics": {key: mean(row["scores"][key] for row in rows if key in row["scores"]) for key in sorted(keys)}}


def publish_experiment(examples, *, dataset_name, retrieval_only=False):
    """Called only by the explicit --publish command; uploads the selected dataset."""
    from langsmith import Client
    from langsmith.evaluation import evaluate
    key = current_app.config.get("LANGSMITH_API_KEY")
    if not key or key in {"replace-me", "replace-with-secret"}:
        raise ValueError("请配置 LANGSMITH_API_KEY")
    app = current_app._get_current_object()
    client = Client(api_key=key, api_url=app.config["LANGSMITH_ENDPOINT"])
    # A fresh dataset prevents silently overwriting curated evaluation labels.
    dataset = client.create_dataset(dataset_name=dataset_name)
    client.create_examples(dataset_id=dataset.id, examples=[{
        "inputs": row.inputs.model_dump(), "outputs": row.outputs.model_dump(),
        "metadata": {"name": row.name},
    } for row in examples])

    def target(inputs):
        with app.app_context():
            return evaluate_input(inputs, retrieval_only=retrieval_only)

    def evaluator(run, example):
        return {"results": [{"key": k, "score": v} for k, v in metrics(run.outputs or {}, example.outputs or {}).items()]}

    return evaluate(target, data=dataset_name, evaluators=[evaluator], client=client,
                    experiment_prefix="kbs-rag-v2", max_concurrency=0,
                    metadata={"pipeline_version": "rag-v2"})
