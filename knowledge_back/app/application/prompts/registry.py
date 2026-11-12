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
    for p in json.loads((Path(__file__).parents[2] / "resources/prompts-v1.json").read_text())
}
_current = ContextVar("prompt_snapshot", default=None)


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
        )
    ).all()
    result = {r.prompt_key: version_data(r) for r in rows}
    if set(result) != set(_BOOTSTRAP):
        raise RuntimeError("提示词尚未初始化，请先升级数据库")
    return result


@contextmanager
def prompt_scope(snapshot=None):
    existing = _current.get()
    if snapshot is None and existing is not None:
        yield existing
        return
    snapshot = snapshot if snapshot is not None else published_snapshot()
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
    snapshot = _current.get()
    if snapshot is not None:
        return snapshot[key]["content"]
    if not has_app_context():
        return bootstrap_content(key)
    return published_snapshot()[key]["content"]


def prompt_metadata():
    snapshot = _current.get() or {}
    return {k: {f: v[f] for f in ("id", "version", "sha256")} for k, v in snapshot.items()}


def prompt_fingerprint():
    return sha256(json.dumps(prompt_metadata(), sort_keys=True).encode()).hexdigest()[:16]
