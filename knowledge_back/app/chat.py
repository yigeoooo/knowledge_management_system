"""Bounded JSON completions for grounded questions and answers."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import current_app


class ChatError(RuntimeError):
    """A safe, user-facing model error; never includes provider response bodies."""


def complete_json(instruction: str, material: dict, *, max_tokens: int = 2048) -> tuple[dict, str]:
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
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        f"{base}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(
            request, timeout=min(90, max(5, config["DEEPSEEK_TIMEOUT_SECONDS"]))
        ) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ChatError("问答模型返回的内容过长，请重试")
        choice = json.loads(raw)["choices"][0]
        if not isinstance(choice, dict):
            raise TypeError
        if choice.get("finish_reason") != "stop":
            raise ChatError("问答模型未完整生成结果，请重试")
        result = json.loads(choice["message"]["content"])
        if not isinstance(result, dict):
            raise TypeError
        return result, model
    except HTTPError as error:
        raise ChatError(f"问答模型服务返回 HTTP {error.code}，请稍后重试") from None
    except (TimeoutError, URLError, OSError):
        raise ChatError("问答模型连接失败或超时，请稍后重试") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ChatError("问答模型返回格式不正确，请重试") from None
