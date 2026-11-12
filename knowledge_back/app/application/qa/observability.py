"""Content-free local execution tree and usage persisted with each business turn."""

from datetime import UTC, datetime
from threading import Lock
from time import monotonic

from langchain_core.callbacks import BaseCallbackHandler

from ..prompts.registry import prompt_fingerprint, prompt_metadata


class RunRecorder(BaseCallbackHandler):
    def __init__(self):
        self.started = {}
        self.steps = []
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.lock = Lock()

    def _start(self, run_id, parent_run_id, name, kind):
        with self.lock:
            if len(self.steps) >= 200:
                return
            step = {"id": str(run_id), "parent_id": str(parent_run_id) if parent_run_id else None,
                    "name": name, "run_type": kind, "status": "running", "latency_ms": None,
                    "started_at": datetime.now(UTC).isoformat()}
            self.steps.append(step)
            self.started[run_id] = (step, monotonic())

    def on_chain_start(self, serialized, inputs, *, run_id, name=None, parent_run_id=None, **kwargs):
        self._start(run_id, parent_run_id, name or (serialized or {}).get("name", "chain"), "chain")

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._start(run_id, parent_run_id, kwargs.get("name") or (serialized or {}).get("name", "chat_model"), "llm")

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        self.on_chat_model_start(serialized, prompts, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None, **kwargs):
        self._start(run_id, parent_run_id, kwargs.get("name") or "knowledge_retriever", "retriever")

    def _finish(self, run_id, failed=False, usage=None):
        with self.lock:
            started = self.started.pop(run_id, None)
            if started:
                step, at = started
                step.update(latency_ms=int((monotonic() - at) * 1000),
                            status="failed" if failed else "success")
                if usage:
                    step.update({k: usage.get(k, 0) or 0 for k in self.usage})
                    for key in self.usage:
                        self.usage[key] += usage.get(key, 0) or 0

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._finish(run_id)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, True)

    on_retriever_end = on_chain_end
    on_retriever_error = on_chain_error
    on_llm_error = on_chain_error

    def on_llm_end(self, response, *, run_id, **kwargs):
        usage = {"input_tokens": 0, "output_tokens": 0}
        for batch in response.generations:
            if batch:
                tokens = getattr(getattr(batch[0], "message", None), "usage_metadata", None) or {}
                for key in usage:
                    usage[key] += tokens.get(key, 0) or 0
        self._finish(run_id, usage=usage)


def record_turn(operation, *, metadata, robot):
    """Include memory compaction and the answer graph under one trace root."""
    from uuid import uuid4

    from flask import current_app
    from langchain_core.runnables import RunnableLambda

    from ...integrations.ai.langsmith_config import tracing_scope
    from ...integrations.ai.langsmith_reader import destination

    recorder, run_id = RunRecorder(), uuid4()
    metadata = {key: str(value) for key, value in metadata.items() if value is not None
                and key in {"conversation_id", "turn_id", "knowledge_base_id", "evaluation_run_id", "evaluation_example_id", "evaluation_arm"}}
    metadata["prompt_versions"] = prompt_metadata()
    metadata["session_id"] = metadata.get("conversation_id", "")

    def details(existing=None):
        return {**(existing or {}), "run_id": str(run_id), "pipeline_version": "rag-v2",
                "prompt_version": prompt_fingerprint(), "prompts": prompt_metadata(), "steps": recorder.steps,
                "token_usage": recorder.usage,
                "destination": destination(current_app.config),
                "content_captured": current_app.config.get("LANGSMITH_CAPTURE_CONTENT", False)}

    try:
        with tracing_scope():
            result = RunnableLambda(operation).invoke({}, config={
                "run_id": run_id, "run_name": "rag.turn", "callbacks": [recorder],
                "metadata": metadata, "tags": ["rag-v2", "robot" if robot else "web"],
            })
    except Exception as error:
        error.execution_trace = details(getattr(error, "execution_trace", None))
        raise
    if result is not None:
        result["execution_trace"] = details(result.get("execution_trace"))
    return result
