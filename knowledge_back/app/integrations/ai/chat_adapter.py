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


def _complete_json_http(
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


def complete_json(instruction, material, *, max_tokens=2048, timeout_seconds=None, schema=None):
    """One bounded provider request; parsing failures never silently call a model twice."""
    from pydantic import ValidationError

    from .langsmith_config import tracing_scope

    with tracing_scope():
        if not current_app.config.get("LANGCHAIN_CHAT_ENABLED", False):
            payload, model = _complete_json_http(
                instruction, material, max_tokens=max_tokens, timeout_seconds=timeout_seconds
            )
            try:
                if schema:
                    payload = schema.model_validate(payload).model_dump()
            except ValidationError:
                raise ChatFormatError("问答模型返回格式不正确") from None
            return payload, model
        return _complete_langchain(
            instruction, material, max_tokens=max_tokens,
            timeout_seconds=timeout_seconds, schema=schema,
        )


def _complete_langchain(instruction, material, *, max_tokens, timeout_seconds, schema):
    from langchain_core.exceptions import OutputParserException
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_deepseek import ChatDeepSeek
    from openai import APIError, APITimeoutError
    from pydantic import ValidationError

    config = current_app.config
    base = config["DEEPSEEK_BASE_URL"].strip().rstrip("/")
    key, model = config["DEEPSEEK_API_KEY"].strip(), config["DEEPSEEK_CHAT_MODEL"].strip()
    if (urlparse(base).scheme not in {"http", "https"} or not urlparse(base).netloc
            or not model or key in {"", "replace-me", "replace-with-secret"}):
        raise ChatError("DeepSeek 问答服务未配置，请联系管理员")
    timeout = min(90, max(5, config["DEEPSEEK_TIMEOUT_SECONDS"]))
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise ChatError("问答处理超时，请稍后重试")
        timeout = min(timeout, timeout_seconds)
    if schema:
        instruction += "\nJSON schema: " + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{instruction}"), ("human", "{material}"),
    ])
    try:
        client = ChatDeepSeek(model=model, api_key=key, api_base=base,
                              timeout=timeout, max_retries=0, temperature=0.1, max_tokens=max_tokens)
        if config.get("LANGCHAIN_STRUCTURED_OUTPUT", True):
            model_call = client.with_structured_output(
                schema, method="json_mode", include_raw=True,
            )
            output = (prompt | model_call).invoke(
                {"instruction": instruction, "material": json.dumps(material, ensure_ascii=False)},
                config={"run_name": "structured." + (schema.__name__ if schema else "json")},
            )
            raw = output["raw"]
            if output.get("parsing_error") is not None:
                raise ChatFormatError("问答模型返回格式不正确")
            payload = output["parsed"]
            if schema:
                payload = schema.model_validate(payload).model_dump()
        else:
            raw = (prompt | client.bind(response_format={"type": "json_object"})).invoke(
                {"instruction": instruction, "material": json.dumps(material, ensure_ascii=False)},
                config={"run_name": "json_completion"},
            )
            payload = _json_object(raw.content)
            if schema:
                payload = schema.model_validate(payload).model_dump()
        if raw.response_metadata.get("finish_reason") != "stop":
            raise ChatFormatError("问答模型未完整生成结果")
        if len(str(raw.content).encode("utf-8")) > 1_048_576:
            raise ChatFormatError("问答模型返回的内容过长")
        if not isinstance(payload, dict):
            raise ChatFormatError("问答模型返回格式不正确")
        return payload, model
    except APITimeoutError:
        raise ChatError("问答模型连接超时，请稍后重试") from None
    except APIError:
        raise ChatError("问答模型服务暂不可用，请稍后重试") from None
    except (ValidationError, OutputParserException, ValueError, KeyError, TypeError):
        raise ChatFormatError("问答模型返回格式不正确") from None
