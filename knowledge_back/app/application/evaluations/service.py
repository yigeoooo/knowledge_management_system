"""Freeze experimental inputs and aggregate paired results without inventing labels."""

import json
from copy import deepcopy
from hashlib import sha256
from statistics import mean
from uuid import UUID

from flask import current_app

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import (
    Document,
    DocumentVersion,
    EvaluationExample,
    KnowledgeBase,
    PromptVersion,
)
from ..prompts.registry import published_snapshot, version_data
from .documents import document_reference

CONFIG_KEYS = (
    "DEEPSEEK_CHAT_MODEL",
    "DEEPSEEK_BASE_URL",
    "LANGCHAIN_CHAT_ENABLED",
    "LANGCHAIN_STRUCTURED_OUTPUT",
    "QA_MIN_SIMILARITY",
    "QA_RERANK_ENABLED",
    "QA_RERANK_PROVIDER",
    "RERANK_MODEL",
    "QA_CONTEXT_TOKEN_BUDGET",
    "DASHSCOPE_EMBEDDING_MODEL",
    "DASHSCOPE_EMBEDDING_DIMENSION",
    "QA_RECENT_TURNS",
    "QA_HISTORY_BUDGET",
    "QWEATHER_HOST",
)


def digest(value):
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def environment(base_id):
    rows = db.session.execute(
        db.select(
            DocumentVersion.id,
            DocumentVersion.content_hash,
            DocumentVersion.index_config_hash,
            DocumentVersion.chunk_count,
            DocumentVersion.updated_at,
        )
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(
            Document.knowledge_base_id == base_id,
            Document.status == "active",
            DocumentVersion.status == "INDEXED",
        )
        .order_by(DocumentVersion.id)
    ).all()
    return {
        "pipeline_version": "conversation-v3-fresh-v1-weather-time-v1",
        "config": {key: current_app.config.get(key) for key in CONFIG_KEYS},
        "index": [
            {
                "id": str(r.id),
                "content_hash": r.content_hash,
                "index_config_hash": r.index_config_hash,
                "chunks": r.chunk_count,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


def prompt_keys_for_input(inputs):
    task = inputs.get("task", "answer")
    if task == "summary":
        return {"summarize"}
    if task == "suggestions":
        return {"suggest_questions", "review_suggestions"}
    covered = {"answer_generate", "review_answer"}
    context = inputs.get("context") or {}
    if inputs.get("robot"):
        covered.update({"robot_persona", "conversation_plan"})
    elif context.get("turns") or context.get("summary"):
        covered.add("conversation_plan")
    return covered


def freeze(dataset, overrides, reviewed_only, *, example_id=None, expected_revision=None):
    base = db.session.get(KnowledgeBase, dataset.knowledge_base_id)
    if not base or base.status != "active":
        raise ApiError("评测知识库不存在或已停用", 409)
    query = db.select(EvaluationExample).where(EvaluationExample.dataset_id == dataset.id)
    if example_id is not None:
        query = query.where(EvaluationExample.id == example_id)
    elif reviewed_only:
        query = query.where(EvaluationExample.reviewed_by.is_not(None))
    examples = db.session.scalars(
        query.order_by(EvaluationExample.created_at, EvaluationExample.id).limit(101)
    ).all()
    if example_id is not None:
        if not examples:
            raise ApiError("测试题不存在或不属于当前评测集", 404)
        if examples[0].revision != expected_revision:
            raise ApiError("测试题已修改，请刷新题目后重新发起单题测试", 409)
    if not examples:
        raise ApiError("没有可用样本，请先保存并启用测试题，或选择包含草稿试测", 422)
    if len(examples) > 100:
        raise ApiError("单次实验最多 100 个样本，请将暂不参与评测的题目保存为草稿，并仅使用已启用题目", 422)
    baseline = published_snapshot()
    candidate = deepcopy(baseline)
    if not isinstance(overrides, dict) or len(overrides) > len(baseline):
        raise ApiError("候选提示词格式不正确", 422)
    for key, value in overrides.items():
        try:
            version = db.session.get(PromptVersion, UUID(str(value)))
        except (ValueError, TypeError):
            raise ApiError("候选版本 ID 不正确", 422) from None
        if key not in candidate or not version or version.prompt_key != key:
            raise ApiError("候选版本与提示词用途不匹配", 422)
        candidate[key] = version_data(version)
    covered = set()
    for example in examples:
        covered.update(prompt_keys_for_input(example.inputs))
    # Samples determine which prompt sections execute; partial coverage is valid.
    # A run may intentionally evaluate only the purposes represented by its questions.
    frozen = [
        {
            "id": str(e.id),
            "name": e.name,
            "revision": e.revision,
            "inputs": {**e.inputs, "knowledge_base_code": base.code},
            "reference": document_reference(e.reference, base.id),
            "reviewed_by": str(e.reviewed_by) if e.reviewed_by else None,
            "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
        }
        for e in examples
    ]
    if "conversation_plan" in candidate:
        from ..realtime.service import VERSION
        for example in frozen:
            spec = example["inputs"].get("realtime")
            if spec is None:
                example["inputs"]["realtime"] = {"runtime": {"now": "2026-01-01T00:00:00+00:00", "timezone": None, "default_location": None, "tool_version": VERSION}, "fixtures": []}
    env = environment(base.id)
    if not env["index"]:
        raise ApiError("知识库还没有完成索引的文档", 409)
    return {
        "pipeline_versions": {"baseline": "conversation-v3" if "conversation_plan" in baseline else "rag-v2", "candidate": "conversation-v3" if "conversation_plan" in candidate else "rag-v2"},
        "scope": "single" if example_id is not None else "dataset",
        "dataset_id": str(dataset.id),
        "dataset_name": dataset.name,
        "knowledge_base_id": str(base.id),
        "knowledge_base_code": base.code,
        "examples": frozen,
        "dataset_hash": digest(frozen),
        "reviewed_only": reviewed_only,
        "covered_prompt_keys": sorted(covered),
        "baseline": baseline,
        "candidate": candidate,
        "environment": env,
        "environment_hash": digest(env),
    }


def prepare_retry(source, dataset, example_id=None):
    """Queue only failed arms, retaining the comparison and all successful results."""
    snapshot = source.snapshot
    base = db.session.get(KnowledgeBase, dataset.knowledge_base_id)
    if not base or base.status != "active":
        raise ApiError("评测知识库不存在或已停用", 409)
    if str(base.id) != snapshot.get("knowledge_base_id") or base.code != snapshot.get("knowledge_base_code"):
        raise ApiError("知识库已变化，请重新发起版本对比", 409)
    if digest(environment(base.id)) != snapshot.get("environment_hash"):
        raise ApiError("知识库索引或运行配置已变化，无法与原结果混合；请重新发起版本对比", 409)
    if not snapshot.get("examples") or not snapshot.get("baseline") or not snapshot.get("candidate"):
        raise ApiError("原实验快照不完整，请重新发起版本对比", 409)
    examples = {e["id"]: e for e in snapshot["examples"]}
    if example_id is not None and example_id not in examples:
        raise ApiError("测试题不属于当前实验", 404)
    results = deepcopy(source.results)
    indexed = {r["id"]: r for r in results}
    selected = []
    for id, example in examples.items():
        if example_id is not None and id != example_id:
            continue
        result = indexed.get(id)
        arms = [arm for arm in ("baseline", "candidate") if not result
                or not result.get(arm) or result[arm].get("error")
                or arm in result.get("retry_pending", [])]
        if not arms:
            continue
        if result is None:
            result = {"id": id, "name": example["name"], "review": None,
                      **{a: {"outputs": {}, "scores": {}, "error": "尚未生成"}
                         for a in ("baseline", "candidate")}}
            results.append(result)
        result["retry_pending"], result["review"] = arms, None
        selected.append(id)
    if not selected:
        raise ApiError("没有可重测的异常题目，正常结果无需重测", 409)
    order = {id: index for index, id in enumerate(examples)}
    results.sort(key=lambda r: order[r["id"]])
    return results, selected


def aggregate(results):
    arms = {}
    for arm in ("baseline", "candidate"):
        rows = [r[arm] for r in results if arm in r]
        keys = {k for r in rows for k in r.get("scores", {})}
        arms[arm] = {
            "count": len(rows),
            "failures": sum(bool(r.get("error")) for r in rows),
            "metrics": {
                k: {
                    "value": mean(r["scores"][k] for r in rows if k in r.get("scores", {})),
                    "count": sum(k in r.get("scores", {}) for r in rows),
                }
                for k in keys
            },
        }
    pairs = [
        r
        for r in results
        if not r.get("retry_pending") and all(a in r and not r[a].get("error") for a in ("baseline", "candidate"))
    ]
    keys = {
        k
        for r in pairs
        for k in r["baseline"].get("scores", {})
        if k in r["candidate"].get("scores", {})
    }
    delta = {
        k: mean(
            r["candidate"]["scores"][k] - r["baseline"]["scores"][k]
            for r in pairs
            if k in r["candidate"]["scores"] and k in r["baseline"]["scores"]
        )
        for k in keys
    }
    reviews = [r["review"] for r in results if r.get("review")]
    ratings = {a: [r[a] for r in reviews if r.get(a) is not None] for a in ("baseline", "candidate")}
    return {
        **arms,
        "paired_count": len(pairs),
        "delta": delta,
        "human_reviewed_count": len(reviews),
        "human_passed_count": sum(r.get("candidate") == 1 for r in reviews),
        "human_failed_count": sum(r.get("candidate") == 0 for r in reviews),
        "human": {
            a: mean(values) if values else None for a, values in ratings.items()
        },
    }
