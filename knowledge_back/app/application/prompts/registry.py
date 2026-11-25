"""Resolve published prompts and freeze their immutable versions per execution."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from hashlib import sha256
from pathlib import Path

from flask import has_app_context

from ...core.extensions import db

_BOOTSTRAP = {
    p["key"]: p
    for filename in ("conversation-v3-v1.json",)
    for p in json.loads((Path(__file__).parents[2] / "resources" / filename).read_text())
}
NEW_KEYS = {"robot_persona", "conversation_plan", "answer_generate", "review_answer",
            "summarize", "suggest_questions", "review_suggestions"}
OLD_ONLY = {"answer_web", "answer_robot", "resolve_web", "resolve_robot", "robot_interaction"}
_current = ContextVar("prompt_snapshot", default=None)
_used = ContextVar("used_prompt_keys", default=None)


def bootstrap_content(key):
    return _BOOTSTRAP[key]["content"]


def version_data(row):
    return {
        "id": str(row.id),
        "version": row.version,
        "content": row.content,
        "sha256": sha256(row.content.encode()).hexdigest(),
    }


def published_snapshot():
    from ...entities import PromptTemplate, PromptVersion

    rows = db.session.scalars(
        db.select(PromptVersion).join(
            PromptTemplate,
            (PromptTemplate.key == PromptVersion.prompt_key)
            & (PromptTemplate.active_version == PromptVersion.version),
        ).where(PromptTemplate.archived.is_(False))
    ).all()
    result = {r.prompt_key: version_data(r) for r in rows}
    if set(result) != NEW_KEYS:
        raise RuntimeError("提示词尚未初始化，请先升级数据库")
    return result


@contextmanager
def prompt_scope(snapshot=None):
    existing = _current.get()
    if snapshot is None and existing is not None:
        yield existing
        return
    snapshot = snapshot if snapshot is not None else published_snapshot()
    if set(snapshot) != NEW_KEYS:
        raise RuntimeError("旧提示词快照已停用，请重新提问或创建新评测")
    token = _current.set(snapshot)
    try:
        yield snapshot
    finally:
        _current.reset(token)


def with_prompts(operation):
    @wraps(operation)
    def invoke(*args, **kwargs):
        if not has_app_context():
            return operation(*args, **kwargs)
        with prompt_scope():
            return operation(*args, **kwargs)

    return invoke


def get_prompt(key):
    used = _used.get()
    if used is not None:
        used.add(key)
    snapshot = _current.get()
    if snapshot is not None:
        return snapshot[key]["content"]
    if not has_app_context():
        return bootstrap_content(key)
    return published_snapshot()[key]["content"]


def has_prompt(key):
    """Old frozen turns must not silently pick up newly published instructions."""
    snapshot = _current.get()
    return key in (snapshot if snapshot is not None else _BOOTSTRAP)


def robot_prompt(key):
    instruction = get_prompt(key)
    from ..robots.identity import identity_prompt
    return identity_prompt(get_prompt("robot_persona") + "\n\n" + instruction if has_prompt("robot_persona") else instruction)


@contextmanager
def track_prompt_usage():
    used = PromptUsage()
    token = _used.set(used)
    try:
        yield used
    finally:
        _used.reset(token)


def prompt_metadata():
    snapshot = _current.get() or {}
    return {k: {f: v[f] for f in ("id", "version", "sha256")} for k, v in snapshot.items()}


def prompt_fingerprint():
    return sha256(json.dumps(prompt_metadata(), sort_keys=True).encode()).hexdigest()[:16]


class PromptUsage(set):
    def __init__(self):
        super().__init__()
        self.compositions = []


def effective_prompt(key, *, robot=False, evidence=()):
    from .composition import compile_prompt
    compiled = compile_prompt(get_prompt(key), channel="robot" if robot else "web", evidence=evidence)
    content = compiled.content
    if robot and key in {"conversation_plan", "answer_generate"}:
        content = get_prompt("robot_persona") + "\n\n" + content
    if robot:
        from ..robots.identity import identity_prompt
        content = identity_prompt(content)
    used = _used.get()
    if used is not None and hasattr(used, "compositions"):
        record = {"key": key, "sections": list(compiled.sections),
                  "channel": "robot" if robot else "web", "evidence": list(evidence),
                  "composer_version": compiled.composer_version,
                  "sha256": sha256(content.encode()).hexdigest()}
        if record not in used.compositions:
            used.compositions.append(record)
    return content
