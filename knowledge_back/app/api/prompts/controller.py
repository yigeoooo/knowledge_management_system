"""Administrator prompt versions. Saving never changes the published release."""

from uuid import UUID

from flask import Blueprint, g, request
from sqlalchemy import func

from ...application.prompts.registry import published_snapshot, version_data
from ...application.prompts.release import release_check, release_reasons
from ...core.extensions import db
from ...core.http import ApiError, success
from ...entities import AuditLog, EvaluationRun, PromptTemplate, PromptVersion
from ..auth.controller import page_required

prompts = Blueprint("prompts", __name__, url_prefix="/api/v1/prompts")


def template(key, lock=False):
    query = db.select(PromptTemplate).where(PromptTemplate.key == key)
    row = db.session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ApiError("提示词用途不存在", 404)
    return row


def serialize(row):
    return {
        "key": row.key,
        "name": row.name,
        "active_version": row.active_version,
        "generation": row.generation,
        "updated_at": row.updated_at.isoformat(),
    }


@prompts.get("")
@page_required("/prompts", "/evaluations")
def list_prompts():
    return success(
        {
            "items": [
                serialize(p)
                for p in db.session.scalars(db.select(PromptTemplate).order_by(PromptTemplate.key))
            ]
        }
    )


@prompts.get("/<key>")
@page_required("/prompts", "/evaluations")
def detail(key):
    row = template(key)
    versions = db.session.scalars(
        db.select(PromptVersion)
        .where(PromptVersion.prompt_key == key)
        .order_by(PromptVersion.version.desc())
    ).all()
    return success(
        {
            **serialize(row),
            "versions": [
                {
                    **version_data(v),
                    "note": v.note,
                    "created_at": v.created_at.isoformat(),
                    "created_by": str(v.created_by) if v.created_by else None,
                }
                for v in versions
            ],
        }
    )


@prompts.post("/<key>/versions")
@page_required("/prompts")
def save_version(key):
    template(key, lock=True)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("请求体必须是 JSON 对象", 422)
    content, note = data.get("content"), data.get("note", "")
    if not isinstance(content, str) or not 20 <= len(content.strip()) <= 20000 or "\x00" in content:
        raise ApiError("提示词正文需为 20–20000 字，不能含空字符", 422)
    if not isinstance(note, str) or len(note) > 1000 or "\x00" in note:
        raise ApiError("修改说明不能超过 1000 字或含空字符", 422)
    latest = db.session.scalar(
        db.select(func.max(PromptVersion.version)).where(PromptVersion.prompt_key == key)
    )
    row = PromptVersion(
        prompt_key=key,
        version=(latest or 0) + 1,
        content=content.strip(),
        note=note.strip(),
        created_by=g.user.id,
    )
    db.session.add(row)
    db.session.flush()
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action="prompt.save",
            resource_type="prompt_version",
            resource_id=row.id,
            detail={"key": key, "version": row.version},
        )
    )
    db.session.commit()
    return success(version_data(row)), 201


@prompts.get("/<key>/versions/<int:number>/release-check")
@page_required("/prompts", "/evaluations")
def check_release(key, number):
    version = db.session.scalar(
        db.select(PromptVersion).where(
            PromptVersion.prompt_key == key, PromptVersion.version == number
        )
    )
    if version is None:
        raise ApiError("提示词版本不存在", 404)
    try:
        dataset_id = UUID(request.args["dataset_id"]) if request.args.get("dataset_id") else None
    except ValueError:
        raise ApiError("评测集 ID 不正确", 422) from None
    return success(release_check(version, dataset_id))


@prompts.post("/<key>/publish")
@page_required("/prompts")
def publish(key):
    # Serialize all publications so another purpose cannot change the tested bundle.
    db.session.scalars(
        db.select(PromptTemplate).order_by(PromptTemplate.key).with_for_update()
    ).all()
    row = template(key)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("请求体必须是 JSON 对象", 422)
    if (
        type(data.get("expected_generation")) is not int
        or data["expected_generation"] != row.generation
    ):
        raise ApiError("发布状态已变化，请刷新后重试", 409)
    if type(data.get("version")) is not int:
        raise ApiError("请选择版本", 422)
    version = db.session.scalar(
        db.select(PromptVersion).where(
            PromptVersion.prompt_key == key, PromptVersion.version == data["version"]
        )
    )
    if version is None:
        raise ApiError("提示词版本不存在", 404)
    try:
        run_id = UUID(str(data.get("evaluation_run_id")))
    except (ValueError, TypeError):
        raise ApiError("发布前必须选择已通过质量评测的实验", 409) from None
    run = db.session.scalar(
        db.select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
    )
    if run is None:
        raise ApiError("评测实验不存在", 404)
    try:
        dataset_id = UUID(str(data.get("dataset_id", run.dataset_id)))
    except ValueError:
        raise ApiError("评测集 ID 不正确", 422) from None
    reasons = release_reasons(version, run, published_snapshot(), lock_examples=True, dataset_id=dataset_id)
    if reasons:
        raise ApiError("不能发布：" + "；".join(reasons), 409)
    before = row.active_version
    row.active_version = version.version
    row.generation += 1
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action="prompt.publish",
            resource_type="prompt_version",
            resource_id=version.id,
            detail={
                "key": key,
                "before": before,
                "after": row.active_version,
                "evaluation_run_id": str(run.id),
                "dataset_id": str(run.dataset_id),
                "knowledge_base_id": run.snapshot["knowledge_base_id"],
                "dataset_hash": run.snapshot["dataset_hash"],
                "environment_hash": run.snapshot["environment_hash"],
            },
        )
    )
    db.session.commit()
    return success(serialize(row))
