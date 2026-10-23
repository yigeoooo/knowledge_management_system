"""Bounded JSON completions for grounded questions and answers."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import current_app


class ChatError(RuntimeError):
    """A safe, user-facing model error; never includes provider response bodies."""


class ChatFormatError(ChatError):
    """Recoverable output failure, distinct from unavailable provider services."""


def _json_object(content):
    # Some compatible gateways wrap otherwise valid JSON in a Markdown fence or
    # return text content blocks. Never repair invalid JSON by guessing its facts.
    if isinstance(content, list) and all(
        isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
        for item in content
    ):
        content = "".join(item["text"] for item in content)
    if not isinstance(content, str):
        raise TypeError
    content = content.strip().lstrip("\ufeff").strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*\n?(.*?)\n?```", content, flags=re.DOTALL | re.IGNORECASE
    )
    result = json.loads(fenced[1].strip() if fenced else content)
    if not isinstance(result, dict):
        raise TypeError
    return result


def complete_json(
    instruction: str,
    material: dict,
    *,
    max_tokens: int = 2048,
    timeout_seconds: float | None = None,
) -> tuple[dict, str]:
    config = current_app.config
    base = config["DEEPSEEK_BASE_URL"].strip().rstrip("/")
    key = config["DEEPSEEK_API_KEY"].strip()
    model = config["DEEPSEEK_CHAT_MODEL"].strip()
    endpoint = urlparse(base)
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.netloc
        or not model
        or key in {"", "replace-me", "replace-with-secret"}
    ):
        raise ChatError("DeepSeek 问答服务未配置，请联系管理员")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(material, ensure_ascii=False)},
        ],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        f"{base}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    timeout = min(90, max(5, config["DEEPSEEK_TIMEOUT_SECONDS"]))
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise ChatError("问答处理超时，请稍后重试")
        timeout = min(timeout, timeout_seconds)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ChatFormatError("问答模型返回的内容过长")
        choice = json.loads(raw)["choices"][0]
        if not isinstance(choice, dict):
            raise TypeError
        if choice.get("finish_reason") != "stop":
            raise ChatFormatError("问答模型未完整生成结果")
        return _json_object(choice["message"]["content"]), model
    except HTTPError as error:
        raise ChatError(f"问答模型服务返回 HTTP {error.code}，请稍后重试") from None
    except (TimeoutError, URLError, OSError):
        raise ChatError("问答模型连接失败或超时，请稍后重试") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ChatFormatError("问答模型返回格式不正确") from None
