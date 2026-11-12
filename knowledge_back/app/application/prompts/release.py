"""A prompt release requires a current, completed, human-approved experiment."""

from uuid import UUID

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import EvaluationDataset, EvaluationExample, EvaluationRun, KnowledgeBase
from ..evaluations.service import digest, environment
from .registry import published_snapshot, version_data


def quality_reasons(run):
    snapshot = run.snapshot
    examples, results = snapshot.get("examples", []), run.results
    reasons = []
    if run.status != "COMPLETED":
        reasons.append("评测尚未成功完成")
    if (
        snapshot.get("reviewed_only") is not True
        or not examples
        or any(not e.get("reviewed_by") or not e.get("reviewed_at") for e in examples)
    ):
        reasons.append("草稿试测不能用于发布，请使用已启用的测试题重新评测")
    if (
        not examples
        or len(results) != len(examples)
        or {r["id"] for r in results} != {e["id"] for e in examples}
    ):
        reasons.append("尚未获得全部测试题的对比结果")
    if any(not r.get(a) or r[a].get("error") for r in results for a in ("baseline", "candidate")):
        reasons.append("存在执行失败的测试题")
    if any(not (r.get("review") or {}).get("reviewed_by") for r in results):
        reasons.append("请逐题完成人工复核")
    if any(r.get("review") and r["review"].get("candidate") != 1 for r in results):
        reasons.append("候选答案存在人工复核不合格项")
    return reasons


def release_reasons(version, run, current, *, lock_examples=False, dataset_id=None):
    reasons = quality_reasons(run)
    snapshot = run.snapshot
    query = db.select(EvaluationDataset).where(EvaluationDataset.id == run.dataset_id)
    dataset = db.session.scalar(query.with_for_update() if lock_examples else query)
    if (
        not dataset
        or (dataset_id is not None and dataset.id != dataset_id)
        or str(dataset.knowledge_base_id) != snapshot.get("knowledge_base_id")
        or snapshot.get("dataset_id", str(run.dataset_id)) != str(run.dataset_id)
    ):
        reasons.append("实验不属于所选知识库当前的唯一评测集，请重新评测")
    if snapshot.get("candidate", {}).get(version.prompt_key) != version_data(version):
        reasons.append("该实验未测试所选提示词版本")
    if version.prompt_key not in snapshot.get("covered_prompt_keys", []):
        reasons.append("测试题未覆盖此提示词用途")
    expected = {**current, version.prompt_key: version_data(version)}
    if snapshot.get("candidate") != expected:
        reasons.append(
            "试测组合与待发布组合不同；请只修改本用途，保持其他用途为当前发布版本后重新评测"
        )
    if snapshot.get("baseline") != current:
        reasons.append("当前发布版本已变化，请以当前版本重新对比评测")
    base = db.session.get(KnowledgeBase, UUID(snapshot["knowledge_base_id"]))
    if (
        not base
        or base.status != "active"
        or base.code != snapshot.get("knowledge_base_code")
        or digest(environment(base.id)) != snapshot.get("environment_hash")
    ):
        reasons.append("知识库索引或运行配置已变化，请重新评测")
    examples = snapshot.get("examples", [])
    query = (
        db.select(EvaluationExample)
        .where(EvaluationExample.dataset_id == run.dataset_id,
               EvaluationExample.reviewed_by.is_not(None))
        .order_by(EvaluationExample.id)
    )
    rows = db.session.scalars(query.with_for_update() if lock_examples else query).all()
    actual = {str(e.id): e for e in rows}
    if set(actual) != {e["id"] for e in examples}:
        reasons.append("评测集的已启用题目范围已变化，请使用当前全部已启用题目重新评测")
    if any(
        e["id"] not in actual
        or actual[e["id"]].revision != e["revision"]
        or not actual[e["id"]].reviewed_by
        for e in examples
    ):
        reasons.append("测试题已修改、删除或改为草稿，请重新评测")
    return reasons


def release_check(version, dataset_id=None):
    current = published_snapshot()
    datasets = [
        {"id": str(dataset.id), "name": dataset.name, "description": dataset.description,
         "knowledge_base_id": str(base.id), "knowledge_base_name": base.name}
        for dataset, base in db.session.execute(
            db.select(EvaluationDataset, KnowledgeBase)
            .join(KnowledgeBase, EvaluationDataset.knowledge_base_id == KnowledgeBase.id)
            .where(KnowledgeBase.status == "active")
            .order_by(KnowledgeBase.name, EvaluationDataset.id)
        )
    ]
    if dataset_id is None and len(datasets) == 1:
        dataset_id = UUID(datasets[0]["id"])
    if dataset_id is not None and not any(item["id"] == str(dataset_id) for item in datasets):
        raise ApiError("评测集不存在或所属知识库已停用", 409)
    if dataset_id is None:
        return {"eligible": False, "evaluation_run_id": None, "dataset_id": None,
                "datasets": datasets, "runs": [], "reasons": [
                    "请选择用于发布验收的知识库评测集" if datasets else "请先为知识库创建评测集并完成质量评测"
                ]}
    runs = db.session.scalars(
        db.select(EvaluationRun)
        .where(
            EvaluationRun.dataset_id == dataset_id,
            EvaluationRun.snapshot["candidate"][version.prompt_key]["id"].as_string()
            == str(version.id)
        )
        .order_by(EvaluationRun.created_at.desc())
    ).all()
    items = []
    for run in runs:
        reasons = release_reasons(version, run, current, dataset_id=dataset_id)
        items.append(
            {"id": str(run.id), "name": run.name, "eligible": not reasons, "reasons": reasons}
        )
    eligible = next((r for r in items if r["eligible"]), None)
    return {
        "eligible": eligible is not None,
        "dataset_id": str(dataset_id),
        "datasets": datasets,
        "evaluation_run_id": eligible["id"] if eligible else None,
        "reasons": []
        if eligible
        else (items[0]["reasons"] if items else ["此版本尚未通过质量评测，请先试测并完成人工复核"]),
        "runs": items,
    }
