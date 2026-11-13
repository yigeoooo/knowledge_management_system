"""Administrator prompt versions. Saving never changes the published release."""

from uuid import UUID

from flask import Blueprint, g, request

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


def is_draft(version, current):
    if version.version == 1 or version.version == current.active_version:
        return False
    return db.session.scalar(db.select(AuditLog.id).where(
        AuditLog.action == "prompt.publish", AuditLog.resource_id == version.id
    ).limit(1)) is None


def serialize(row):
    return {
        "key": row.key,
        "name": row.name,
        "active_version": row.active_version,
        "generation": row.generation,
        "archived": row.archived,
        "updated_at": row.updated_at.isoformat(),
    }


@prompts.get("")
@page_required("/prompts", "/evaluations")
def list_prompts():
    return success(
        {
            "items": [
                serialize(p)
                for p in db.session.scalars(db.select(PromptTemplate).where(PromptTemplate.archived.is_(False) if request.args.get("include_archived") != "1" else True).order_by(PromptTemplate.key))
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
                    "is_draft": is_draft(v, row),
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
    row_template = template(key, lock=True)
    if row_template.archived:
        raise ApiError("历史用途仅供查看", 409)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("请求体必须是 JSON 对象", 422)
    content, note = data.get("content"), data.get("note", "")
    if not isinstance(content, str) or not 20 <= len(content.strip()) <= 20000 or "\x00" in content:
        raise ApiError("提示词正文需为 20–20000 字，不能含空字符", 422)
    if not isinstance(note, str) or len(note) > 1000 or "\x00" in note:
        raise ApiError("修改说明不能超过 1000 字或含空字符", 422)
    import json

    from ...application.prompts.composition import compile_prompt
    if key in {"conversation_plan", "answer_generate"}:
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict) or parsed.get("format") != "kbs-prompt-sections-v1":
                raise ValueError()
        except ValueError:
            raise ApiError("新用途必须使用结构化分区编辑", 422) from None
    try:
        compile_prompt(content, channel="robot", evidence=("knowledge", "realtime"))
    except ValueError as error:
        raise ApiError(str(error), 422) from None
    latest = db.session.scalar(
        db.select(PromptVersion).where(PromptVersion.prompt_key == key)
        .order_by(PromptVersion.version.desc()).with_for_update()
    )
    selected = None
    if data.get("base_version_id"):
        try:
            selected = db.session.get(PromptVersion, UUID(data["base_version_id"]))
        except (ValueError, TypeError):
            raise ApiError("版本 ID 不正确", 422) from None
        if selected is None or selected.prompt_key != key:
            raise ApiError("提示词版本不存在", 404)
    # Always target the single latest unpublished draft. A stale or omitted
    # selection must never create another draft number.
    if latest is not None and is_draft(latest, row_template):
        if selected is None:
            selected = latest
        elif selected.id != latest.id:
            raise ApiError("请刷新后编辑当前草稿", 409)
    updating = selected is not None and is_draft(selected, row_template)
    if updating:
        if data.get("expected_sha256") != version_data(selected)["sha256"] or data.get("expected_note") != selected.note:
            raise ApiError("草稿已被修改，请刷新后重试", 409)
        row = selected
        row.content = content.strip()
        row.note = note.strip()
    else:
        row = PromptVersion(prompt_key=key, version=(latest.version if latest else 0) + 1,
                            content=content.strip(), note=note.strip(), created_by=g.user.id)
        db.session.add(row)
    db.session.flush()
    db.session.add(
        AuditLog(
            user_id=g.user.id,
            action="prompt.save",
            resource_type="prompt_version",
            resource_id=row.id,
            detail={"key": key, "version": row.version, "updated_draft": updating},
        )
    )
    db.session.commit()
    return success(version_data(row)), 200 if updating else 201


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

@prompts.post("/publish-bundle")
@page_required("/prompts")
def publish_bundle():
    data = request.get_json(silent=True) or {}
    try:
        run_id = UUID(str(data.get("evaluation_run_id")))
    except (ValueError, TypeError):
        raise ApiError("发布前必须选择已通过质量评测的实验", 409) from None
    db.session.scalars(db.select(PromptTemplate).order_by(PromptTemplate.key).with_for_update()).all()
    run = db.session.scalar(db.select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update())
    if not run:
        raise ApiError("评测实验不存在", 404)
    versions = bundle_versions(run, lock=True)
    for version in versions:
        row = template(version.prompt_key, lock=True)
        db.session.add(AuditLog(user_id=g.user.id, action="prompt.publish",
            resource_type="prompt_version", resource_id=version.id,
            detail={"key": version.prompt_key, "before": row.active_version,
                    "after": version.version, "evaluation_run_id": str(run.id), "bundle": True}))
        row.active_version = version.version
        row.generation += 1
    db.session.commit()
    return success({"published": [v.prompt_key for v in versions]})


def bundle_versions(run, *, lock=False):
    candidate = run.snapshot.get("candidate", {})
    current = published_snapshot()
    if set(candidate) != set(current):
        raise ApiError("实验提示词组合不完整，请重新评测", 409)
    versions = []
    for key, item in candidate.items():
        if item == current.get(key):
            continue
        version = db.session.scalar(db.select(PromptVersion).where(PromptVersion.id == UUID(item["id"])))
        if not version:
            raise ApiError("候选提示词版本不存在", 404)
        reasons = release_reasons(version, run, current, lock_examples=lock, dataset_id=run.dataset_id, bundle=True)
        if reasons:
            raise ApiError("不能发布：" + "；".join(reasons), 409)
        versions.append(version)
    if not versions:
        raise ApiError("本次实验没有需要发布的提示词修改", 409)
    return versions


@prompts.get("/bundle-release-check/<uuid:run_id>")
@page_required("/prompts")
def bundle_release_check(run_id):
    run = db.session.get(EvaluationRun, run_id)
    if run is None:
        raise ApiError("评测实验不存在", 404)
    try:
        versions = bundle_versions(run)
    except ApiError as error:
        return success({"eligible": False, "reasons": [str(error)]})
    return success({"eligible": True, "keys": [v.prompt_key for v in versions], "reasons": []})
