"""Per-application tracing with explicit opt-in and no process environment mutation."""
from contextlib import contextmanager
from contextvars import ContextVar

from flask import current_app, has_app_context
from langsmith import Client, tracing_context

_active = ContextVar("kbs_tracing_active", default=False)


def configure_langsmith(config):
    key = str(config.get("LANGSMITH_API_KEY") or "").strip()
    if not config.get("LANGSMITH_TRACING") or key in {"", "replace-me", "replace-with-secret"}:
        return None
    try:
        return Client(
            api_url=config["LANGSMITH_ENDPOINT"], api_key=key,
            hide_inputs=not config.get("LANGSMITH_CAPTURE_CONTENT", False),
            hide_outputs=not config.get("LANGSMITH_CAPTURE_CONTENT", False),
            omit_traced_runtime_info=True,
            tracing_sampling_rate=max(0.0, min(1.0, config["LANGSMITH_SAMPLING_RATE"])),
            timeout_ms=2000, auto_batch_tracing=True,
        )
    except Exception:  # noqa: BLE001 - optional telemetry must not stop startup
        # Observability configuration cannot take down the answer service.
        return None


@contextmanager
def tracing_scope():
    if _active.get():
        yield
        return
    client = current_app.extensions.get("langsmith") if has_app_context() else None
    project = current_app.config.get("LANGSMITH_PROJECT") if has_app_context() else None
    token = _active.set(True)
    try:
        # This explicitly disables ambient LANGCHAIN_TRACING_V2 as well.
        destination = {"project_name": project}
        if has_app_context() and current_app.config.get("LANGSMITH_AGENT_ID"):
            from langsmith import agent_address
            destination = {"address": agent_address(current_app.config["LANGSMITH_AGENT_ID"],
                                  current_app.config["LANGSMITH_AGENT_ENVIRONMENT"])}
        with tracing_context(enabled=client is not None, client=client, **destination):
            yield
    finally:
        _active.reset(token)
