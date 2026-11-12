"""Administrative curation and paired prompt experiments."""

import json
from uuid import UUID

from flask import Blueprint, current_app, g, request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from ...application.documents.preview import preview_version
from ...application.evaluations import history as history_source
from ...application.evaluations.documents import document_reference
from ...application.evaluations.service import aggregate, freeze
from ...application.prompts.release import quality_reasons
from ...application.qa.evaluation import EvaluationInput, Reference
from ...core.extensions import db
from ...core.http import ApiError, success
from ...entities import (
    AuditLog,
    Document,
    DocumentVersion,
    EvaluationDataset,
    EvaluationExample,
    EvaluationRun,
    KnowledgeBase,
    now,
)
from ...security.permissions import require_page_access
from ..auth.controller import page_required

experiments = Blueprint("evaluations", __name__, url_prefix="/api/v1/evaluations")


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("请求体必须是 JSON 对象", 422)
    return data


def text(value, label, limit=200):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or "\x00" in value:
        raise ApiError(f"{label}需为 1–{limit} 字且不能含空字符", 422)
    return value.strip()


def find(model, id, lock=False):
    query = db.select(model).where(model.id == id)
    row = db.session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ApiError("记录不存在", 404)
    return row


def lock_example(id):
    dataset_id = db.session.scalar(db.select(EvaluationExample.dataset_id).where(EvaluationExample.id == id))
    if dataset_id is None:
        raise ApiError("记录不存在", 404)
    # All membership changes serialize with freezing and publication on the parent set.
    find(EvaluationDataset, dataset_id, lock=True)
    return find(EvaluationExample, id, lock=True)


def audit(action, row, detail=None):
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action=action,
            resource_type=row.__tablename__,
            resource_id=row.id,
            detail=detail or {},
        )
    )


def example_data(row):
    reference = row.reference
    issue = None
    try:
        reference = document_reference(
            reference, find(EvaluationDataset, row.dataset_id).knowledge_base_id
        )
    except ApiError as error:
        issue = error.message
    return {
        "id": str(row.id),
        "name": row.name,
        "inputs": row.inputs,
        "reference": reference,
        "document_issue": issue,
        "revision": row.revision,
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "status": "enabled" if row.reviewed_by else "draft",
    }


def run_data(row, details=False):
    result = {
        "id": str(row.id),
        "dataset_id": str(row.dataset_id),
        "name": row.name,
        "status": row.status,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat(),
        "total": len(row.snapshot["examples"]),
        "completed": len(row.results),
        "reviewed_only": row.snapshot["reviewed_only"],
        "summary": aggregate(row.results),
        "quality_reasons": quality_reasons(row),
    }
    if details:
        result.update(snapshot=row.snapshot, results=row.results)
    return result


def wake():
    from ...workers.evaluation_worker import schedule_worker

    if current_app.config.get("EVALUATION_WORKER_AUTOSTART", True) and not current_app.testing:
        schedule_worker(current_app._get_current_object())


@experiments.get("/options")
@page_required("/evaluations")
def options():
    return success(
        {
            "knowledge_bases": [
                {"id": str(b.id), "name": b.name, "code": b.code,
                 "dataset_id": str(dataset_id) if dataset_id else None}
                for b, dataset_id in db.session.execute(
                    db.select(KnowledgeBase, EvaluationDataset.id)
                    .outerjoin(EvaluationDataset, EvaluationDataset.knowledge_base_id == KnowledgeBase.id)
                    .where(KnowledgeBase.status == "active")
                    .order_by(KnowledgeBase.name)
                )
            ]
        }
    )


@experiments.get("/datasets")
@page_required("/evaluations")
def datasets():
    return success(
        {
            "items": [
                {
                    "id": str(d.id),
                    "name": d.name,
                    "description": d.description,
                    "knowledge_base_id": str(d.knowledge_base_id),
                    "knowledge_base_name": b.name,
                }
                for d, b in db.session.execute(
                    db.select(EvaluationDataset, KnowledgeBase)
                    .join(KnowledgeBase, EvaluationDataset.knowledge_base_id == KnowledgeBase.id)
                    .order_by(EvaluationDataset.created_at.desc())
                    .limit(200)
                )
            ]
        }
    )


@experiments.post("/datasets")
@page_required("/evaluations")
def create_dataset():
    data = body()
    try:
        base = find(KnowledgeBase, UUID(str(data.get("knowledge_base_id"))), lock=True)
    except ValueError:
        raise ApiError("知识库 ID 不正确", 422) from None
    if base.status != "active":
        raise ApiError("知识库已停用", 409)
    if db.session.scalar(db.select(EvaluationDataset.id).where(EvaluationDataset.knowledge_base_id == base.id)):
        raise ApiError("此知识库已有评测集，请在现有评测集中维护测试题", 409)
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 2000 or "\x00" in description:
        raise ApiError("说明不能超过 2000 字或含空字符", 422)
    row = EvaluationDataset(
        name=text(data.get("name"), "评测集名称"),
        knowledge_base_id=base.id,
        description=description,
        created_by=g.user.id,
    )
    db.session.add(row)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("此知识库已有评测集，请刷新后使用现有评测集", 409) from None
    audit("evaluation.dataset.create", row)
    db.session.commit()
    return success({"id": str(row.id)}), 201


@experiments.get("/datasets/<uuid:id>/examples")
@page_required("/evaluations")
def examples(id):
    find(EvaluationDataset, id)
    return success(
        {
            "items": [
                example_data(e)
                for e in db.session.scalars(
                    db.select(EvaluationExample)
                    .where(EvaluationExample.dataset_id == id)
                    .order_by(EvaluationExample.created_at, EvaluationExample.id)
                )
            ]
        }
    )


@experiments.get("/datasets/<uuid:id>/documents")
@page_required("/evaluations")
def dataset_documents(id):
    dataset = find(EvaluationDataset, id)
    if find(KnowledgeBase, dataset.knowledge_base_id).status != "active":
        raise ApiError("评测知识库已停用", 409)
    query = (
        db.select(Document, DocumentVersion)
        .outerjoin(DocumentVersion, Document.current_version_id == DocumentVersion.id)
        .where(Document.knowledge_base_id == dataset.knowledge_base_id, Document.status == "active")
    )
    search = request.args.get("q", "").strip()[:200]
    matching = query.where(Document.title.icontains(search, autoescape=True)) if search else query
    rows = db.session.execute(matching.order_by(Document.title, Document.id).limit(50)).all()
    try:
        selected = [UUID(value) for value in request.args.getlist("selected")[:30]]
    except ValueError:
        raise ApiError("所选文档 ID 格式不正确", 422) from None
    if selected:
        rows.extend(db.session.execute(query.where(Document.id.in_(selected))).all())
    return success(
        {
            "items": list(
                {
                    str(doc.id): {
                        "id": str(doc.id),
                        "title": doc.title,
                        "filename": version.filename if version else "",
                        "indexed": bool(version and version.status == "INDEXED"),
                    }
                    for doc, version in rows
                }.values()
            )
        }
    )


@experiments.get("/datasets/<uuid:id>/documents/<uuid:document_id>/preview")
@page_required("/evaluations")
def preview_document(id, document_id):
    dataset = find(EvaluationDataset, id)
    if find(KnowledgeBase, dataset.knowledge_base_id).status != "active":
        raise ApiError("评测知识库已停用", 409)
    document = db.session.scalar(
        db.select(Document).where(
            Document.id == document_id,
            Document.knowledge_base_id == dataset.knowledge_base_id,
            Document.status == "active",
        )
    )
    if document is None:
        raise ApiError("文档不存在或不属于本评测集知识库", 404)
    version = (
        db.session.get(DocumentVersion, document.current_version_id)
        if document.current_version_id
        else None
    )
    if (
        not version
        or version.document_id != document.id
        or version.status in {"PENDING_UPLOAD", "ARCHIVED"}
    ):
        raise ApiError("文档还没有可预览的版本", 409)
    return success(
        {
            "document": {
                "id": str(document.id),
                "title": document.title,
                "indexed": version.status == "INDEXED",
            },
            "version": {
                "id": str(version.id),
                "number": version.version_no,
                "filename": version.filename,
            },
            **preview_version(version),
        }
    )


def history_scope(id):
    # Both permissions are required; access to evaluation authoring alone cannot read logs.
    require_page_access("/qa-logs")
    dataset = find(EvaluationDataset, id)
    if find(KnowledgeBase, dataset.knowledge_base_id).status != "active":
        raise ApiError("评测知识库已停用", 409)
    source = request.args.get("source_type")
    if source not in {"WEB", "ROBOT"}:
        raise ApiError("请选择用户或机器人来源", 422)
    return dataset.knowledge_base_id, source


def history_number(key, default, maximum=100000):
    try:
        value = int(request.args.get(key, default))
    except (TypeError, ValueError):
        raise ApiError("分页或轮次参数不正确", 422) from None
    if not 1 <= value <= maximum:
        raise ApiError("分页或轮次参数超出范围", 422)
    return value


@experiments.get("/datasets/<uuid:id>/history/owners")
@page_required("/evaluations")
def history_owners(id):
    base, source = history_scope(id)
    return success(history_source.owners(base, source, request.args.get("q", "").strip()[:200],
                                         history_number("page", 1), history_number("page_size", 20, 50)))


@experiments.get("/datasets/<uuid:id>/history/conversations")
@page_required("/evaluations")
def history_conversations(id):
    base, source = history_scope(id)
    try:
        owner_id = UUID(request.args.get("owner_id", ""))
    except ValueError:
        raise ApiError("请选择用户或机器人", 422) from None
    return success(history_source.history(base, source, owner_id, request.args.get("q", "").strip()[:200],
                                          history_number("page", 1), history_number("page_size", 20, 50)))


@experiments.get("/datasets/<uuid:id>/history/conversations/<uuid:cid>/turns")
@page_required("/evaluations")
def history_turns(id, cid):
    row = history_source.conversation(*history_scope(id), cid)
    return success(history_source.turns(row, history_number("page", 1), history_number("page_size", 10, 50)))


@experiments.get("/datasets/<uuid:id>/history/conversations/<uuid:cid>/context")
@page_required("/evaluations")
def history_context(id, cid):
    row = history_source.conversation(*history_scope(id), cid)
    return success(history_source.context_copy(row, history_number("start", None),
                                               history_number("end", None), request.args.get("task")))


def validate_example(data, dataset):
    base = find(KnowledgeBase, dataset.knowledge_base_id)
    if base.status != "active":
        raise ApiError("评测知识库已停用", 409)
    try:
        raw_inputs = data.get("inputs", {})
        if not isinstance(raw_inputs, dict):
            raise TypeError()
        inputs = EvaluationInput.model_validate({**raw_inputs, "knowledge_base_code": base.code})
        reference = Reference.model_validate(data.get("reference", {}))
    except (ValidationError, ValueError, TypeError):
        raise ApiError("题目或参考答案格式不正确", 422) from None
    if len(json.dumps(inputs.context, ensure_ascii=False)) > 20000:
        raise ApiError("历史语境不能超过 20000 字", 422)
    if inputs.task == "summary":
        turns = inputs.context.get("turns")
        if not isinstance(turns, list) or not turns or any(not isinstance(t, dict) for t in turns):
            raise ApiError("摘要测试需填写非空的历史 turns 数组", 422)
        if len(json.dumps(turns, ensure_ascii=False).encode()) > 18000:
            raise ApiError("摘要测试的历史内容超过 18000 字节，请缩短样本", 422)
    if reference.expected_status not in {
        None,
        "SUCCESS",
        "PARTIAL",
        "NO_EVIDENCE",
        "SOURCES_ONLY",
        "CLARIFICATION",
    }:
        raise ApiError("预期回答状态不正确", 422)
    for values in (
        reference.expected_documents,
        reference.answer_points,
        reference.forbidden_points,
    ):
        if len(values) > 30 or any(not 1 <= len(v.strip()) <= 1000 or "\x00" in v for v in values):
            raise ApiError("每组标注最多 30 条，每条需为 1–1000 字", 422)
    return (
        text(data.get("name"), "样本名称"),
        inputs.model_dump(),
        document_reference(reference.model_dump(), base.id),
    )


def set_example_status(row, status):
    if status not in ("draft", "enabled"):
        raise ApiError("测试题状态只能是 draft 或 enabled", 422)
    if status == "enabled":
        context = row.inputs.get("context") or {}
        turns = context.get("turns", [])
        if (
            not isinstance(turns, list)
            or len(turns) > 30
            or any(
                not isinstance(t, dict)
                or any(
                    not isinstance(t.get(k), str) or not t[k].strip()
                    for k in ("question", "answer")
                )
                for t in turns
            )
        ):
            raise ApiError("启用前请补全历史问题和回答，最多 30 轮；未完成时可保存草稿", 422)
        if not any(
            row.reference.get(k)
            for k in ("answer_points", "expected_document_ids", "expected_status")
        ):
            raise ApiError(
                "启用前请至少填写答案要点、预期文档或预期状态；未完成的题目可保存草稿", 422
            )
        row.reviewed_by, row.reviewed_at = g.user.id, now()
    else:
        row.reviewed_by = row.reviewed_at = None


@experiments.post("/datasets/<uuid:id>/examples")
@page_required("/evaluations")
def add_example(id):
    dataset = find(EvaluationDataset, id, lock=True)
    data = body()
    name, inputs, reference = validate_example(data, dataset)
    count = db.session.scalar(
        db.select(db.func.count())
        .select_from(EvaluationExample)
        .where(EvaluationExample.dataset_id == id)
    )
    if count >= 100:
        raise ApiError("单个评测集最多 100 个样本", 422)
    if db.session.scalar(
        db.select(EvaluationExample.id).where(
            EvaluationExample.dataset_id == id, EvaluationExample.name == name
        )
    ):
        raise ApiError("样本名称已存在", 409)
    row = EvaluationExample(
        dataset_id=id, name=name, inputs=inputs, reference=reference, created_by=g.user.id
    )
    set_example_status(row, data.get("status", "draft"))
    db.session.add(row)
    db.session.flush()
    audit(
        "evaluation.example.create",
        row,
        {"status": "enabled" if row.reviewed_by else "draft", "revision": row.revision},
    )
    db.session.commit()
    return success(example_data(row)), 201


@experiments.put("/examples/<uuid:id>")
@page_required("/evaluations")
def edit_example(id):
    row = lock_example(id)
    data = body()
    if data.get("expected_revision") != row.revision:
        raise ApiError("题目已被修改，请刷新后重试", 409)
    name, inputs, reference = validate_example(data, find(EvaluationDataset, row.dataset_id))
    if db.session.scalar(
        db.select(EvaluationExample.id).where(
            EvaluationExample.dataset_id == row.dataset_id,
            EvaluationExample.name == name,
            EvaluationExample.id != id,
        )
    ):
        raise ApiError("样本名称已存在", 409)
    row.name, row.inputs, row.reference = name, inputs, reference
    row.revision += 1
    set_example_status(row, data.get("status", "draft"))
    audit(
        "evaluation.example.edit",
        row,
        {"revision": row.revision, "status": "enabled" if row.reviewed_by else "draft"},
    )
    db.session.commit()
    return success(example_data(row))


@experiments.post("/examples/<uuid:id>/review")
@page_required("/evaluations")
def review_example(id):
    # Compatibility for older clients. The current UI enables a sample during save.
    row = lock_example(id)
    data = body()
    if data.get("expected_revision") != row.revision:
        raise ApiError("题目已变化，请重新核对资料", 409)
    if data.get("confirmed") is not True:
        raise ApiError("请确认已按原始资料核对标注", 422)
    row.reference = document_reference(
        row.reference, find(EvaluationDataset, row.dataset_id).knowledge_base_id
    )
    set_example_status(row, "enabled")
    audit("evaluation.example.review", row, {"revision": row.revision})
    db.session.commit()
    return success(example_data(row))


@experiments.delete("/examples/<uuid:id>")
@page_required("/evaluations")
def delete_example(id):
    row = lock_example(id)
    if body().get("expected_revision") != row.revision:
        raise ApiError("题目已变化，请刷新后重试", 409)
    audit("evaluation.example.delete", row)
    db.session.delete(row)
    db.session.commit()
    return success({})


@experiments.post("/runs")
@page_required("/evaluations")
def create_run():
    data = body()
    try:
        dataset = find(EvaluationDataset, UUID(str(data.get("dataset_id"))), lock=True)
    except ValueError:
        raise ApiError("评测集 ID 不正确", 422) from None
    pending = db.session.scalar(
        db.select(db.func.count())
        .select_from(EvaluationRun)
        .where(EvaluationRun.status.in_(["PENDING", "RUNNING"]))
    )
    if pending >= 3:
        raise ApiError("已有多个评测任务，请等待完成", 409)
    reviewed_only = data.get("reviewed_only", True)
    if type(reviewed_only) is not bool:
        raise ApiError("reviewed_only 必须是布尔值", 422)
    snapshot = freeze(dataset, data.get("overrides", {}), reviewed_only)
    row = EvaluationRun(
        dataset_id=dataset.id,
        name=text(data.get("name"), "实验名称"),
        snapshot=snapshot,
        created_by=g.user.id,
    )
    db.session.add(row)
    db.session.flush()
    audit(
        "evaluation.run.create",
        row,
        {"dataset_hash": snapshot["dataset_hash"], "reviewed_only": reviewed_only},
    )
    db.session.commit()
    result = run_data(row)
    wake()
    return success(result), 202


@experiments.get("/runs")
@page_required("/evaluations")
def runs():
    query = db.select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(50)
    rows = db.session.scalars(query).all()
    result = [run_data(r) for r in rows]
    db.session.rollback()
    wake()
    return success({"items": result})


@experiments.get("/runs/<uuid:id>")
@page_required("/evaluations")
def run_detail(id):
    result = run_data(find(EvaluationRun, id), True)
    db.session.rollback()
    wake()
    return success(result)


@experiments.post("/runs/<uuid:id>/reviews/<uuid:example_id>")
@page_required("/evaluations")
def review_result(id, example_id):
    row = find(EvaluationRun, id, lock=True)
    data = body()
    if row.status not in {"COMPLETED", "FAILED"}:
        raise ApiError("请等待评测结束后复核结果", 409)
    if type(data.get("candidate")) is not int or data["candidate"] not in (0, 1):
        raise ApiError("请选择本题候选答案是否合格", 422)
    # Older clients may still submit a separate baseline rating.
    if "baseline" in data and (type(data["baseline"]) is not int or data["baseline"] not in (0, 1)):
        raise ApiError("基线答案合格标记需为 0 或 1", 422)
    note = data.get("note", "")
    if not isinstance(note, str) or len(note.strip()) > 2000 or "\x00" in note:
        raise ApiError("复核说明需为不超过 2000 字的文本且不能含空字符", 422)
    updated = json.loads(json.dumps(row.results))
    result = next((r for r in updated if r["id"] == str(example_id)), None)
    if result is None:
        raise ApiError("评测结果不存在", 404)
    if any(not result.get(arm) or result[arm].get("error") for arm in ("baseline", "candidate")):
        raise ApiError("运行失败的答案不能作为质量合格样本", 409)
    previous_baseline = (result.get("review") or {}).get("baseline")
    result["review"] = {
        "candidate": data["candidate"],
        "note": note.strip(),
        "reviewed_by": str(g.user.id),
        "reviewed_at": now().isoformat(),
    }
    baseline = data.get("baseline", previous_baseline)
    if baseline is not None:
        result["review"]["baseline"] = baseline
    row.results = updated
    audit("evaluation.result.review", row, {"example_id": str(example_id), **result["review"]})
    db.session.commit()
    return success(run_data(row, True))
