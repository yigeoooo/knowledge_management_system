"""Administrator-only projection of one persisted turn's execution, never arbitrary run IDs."""

import re
from urllib.parse import urlsplit, urlunsplit

from flask import current_app

from ...integrations.ai.langsmith_reader import read_run_tree

MAX_RUNS = 200
SECRET = re.compile(r"api[_-]?key|authorization|password|secret|credential|access_token|refresh_token", re.IGNORECASE)


def safe_data(value, depth=0):
    """Bound trace payloads and remove transport credentials and signed object URLs."""
    if depth > 12:
        return "[层级过深，已省略]"
    if isinstance(value, dict):
        return {str(k): "[已隐藏]" if SECRET.search(str(k)) else safe_data(v, depth + 1)
                for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        items = [safe_data(v, depth + 1) for v in value[:100]]
        return items + (["[其余内容已省略]"] if len(value) > 100 else [])
    if isinstance(value, str):
        value = re.sub(r"(?:lsv2_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|Bearer\s+[^\s\"']+)", "[已隐藏]", value)
        def clean_url(match):
            try:
                url = urlsplit(match[0])
                return urlunsplit((url.scheme, url.netloc.split("@")[-1], url.path, "", ""))
            except ValueError:
                return "[URL 已隐藏]"
        value = re.sub(r"https?://[^\s\"<>]+", clean_url, value)
        return value[:16000] + ("\n[内容过长，已截取]" if len(value) > 16000 else "")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return safe_data(str(value), depth + 1)


def _run_data(run):
    start, end = run.start_time, run.end_time
    return {
        "id": str(run.id), "parent_id": (run.dotted_order.split(".")[-2][-36:] if run.dotted_order and "." in run.dotted_order else None),
        "name": run.name, "run_type": run.run_type,
        "status": "failed" if run.error else "success" if end else "running",
        "started_at": start.isoformat() if start else None,
        "latency_ms": max(0, int((end - start).total_seconds() * 1000)) if end and start else None,
        "input_tokens": getattr(run, "prompt_tokens", None),
        "output_tokens": getattr(run, "completion_tokens", None),
        "total_tokens": getattr(run, "total_tokens", None),
        "inputs": safe_data(run.inputs), "outputs": safe_data(run.outputs),
        "error": safe_data(run.error),
    }


def get_trace_details(log):
    local = log.execution_trace or {}
    result = {
        "turn_id": str(log.id), "conversation_id": str(log.conversation_id),
        "question": log.question, "status": log.status, "latency_ms": log.latency_ms,
        "resolved_question": log.resolved_question,
        "local": {**safe_data(local), "steps": [safe_data(step) for step in local.get("steps", [])[:MAX_RUNS]]},
        "source": "local", "runs": [], "truncated": False,
        "message": "此历史记录未保存流程追踪；升级后发起的问题会记录处理流程。",
        "content_captured": bool(local.get("content_captured", False)),
    }
    run_id = local.get("run_id")
    if not run_id:
        return result
    client = current_app.extensions.get("langsmith")
    if client is None:
        result["message"] = "LangSmith 未启用，当前展示本地保存的流程诊断。"
        return result
    try:
        records = read_run_tree(current_app.config, client, local, MAX_RUNS)
        root = next(run for run in records if str(run.id) == run_id)
        # Only the saved root and its descendants belong to this business turn.
        # Ignore siblings even if an upstream caller joined several turns in a trace.
        prefix = root.dotted_order + "." if root.dotted_order else None
        runs = [root]
        for run in records:
            if str(run.id) == str(root.id):
                continue
            if prefix and (run.dotted_order or "").startswith(prefix):
                runs.append(run)
        result["truncated"] = len(records) > MAX_RUNS
        result["runs"] = [_run_data(run) for run in sorted(
            runs[:MAX_RUNS], key=lambda r: r.dotted_order or str(r.id))]
        result["runs"][0]["parent_id"] = None
        result["source"] = "langsmith"
        result["message"] = "已读取 LangSmith 追踪。新记录的步骤可能仍在同步，可点击刷新。"
    except Exception as error:  # noqa: BLE001 - telemetry failure cannot hide business history
        current_app.logger.info("trace read unavailable turn=%s type=%s", log.id, type(error).__name__)
        result["message"] = "LangSmith 记录暂未同步、已过保留期或服务不可用，当前展示本地诊断，可稍后刷新。"
    return result
