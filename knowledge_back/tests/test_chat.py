"""The provider boundary rejects truncated/malformed output without leaking payloads."""

import importlib
import json
from io import BytesIO
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from flask import Flask

chat_module = importlib.import_module("app.chat")


@pytest.fixture
def chat_context():
    app = Flask(__name__)
    app.config.update(
        DEEPSEEK_BASE_URL="https://chat.test/v1/",
        DEEPSEEK_API_KEY="test-secret",
        DEEPSEEK_CHAT_MODEL="test-chat",
        DEEPSEEK_TIMEOUT_SECONDS=60,
    )
    with app.app_context():
        yield app


def test_json_completion_sends_bounded_nonstream_request(chat_context, monkeypatch):
    body = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"questions": []}),
                },
            }
        ]
    }
    transport = Mock(return_value=BytesIO(json.dumps(body).encode()))
    monkeypatch.setattr(chat_module, "urlopen", transport)
    assert chat_module.complete_json("JSON instruction", {"sources": []}) == (
        {"questions": []},
        "test-chat",
    )
    request = transport.call_args.args[0]
    assert request.full_url == "https://chat.test/v1/chat/completions"
    payload = json.loads(request.data)
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert transport.call_args.kwargs["timeout"] == 60


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b'{"choices": []}',
        b'{"choices": [null]}',
        b'{"choices": [{"finish_reason": "length"}]}',
        b'{"choices": [{"finish_reason": "stop", "message": {"content": "[]"}}]}',
        b"x" * 1_048_577,
    ],
)
def test_malformed_or_incomplete_completion_fails_safely(chat_context, monkeypatch, body):
    monkeypatch.setattr(chat_module, "urlopen", Mock(return_value=BytesIO(body)))
    with pytest.raises(chat_module.ChatError):
        chat_module.complete_json("JSON instruction", {})


def test_provider_error_does_not_expose_body_or_key(chat_context, monkeypatch):
    error = HTTPError("https://chat.test", 401, "test-secret", {}, BytesIO(b"private payload"))
    monkeypatch.setattr(chat_module, "urlopen", Mock(side_effect=error))
    with pytest.raises(chat_module.ChatError) as raised:
        chat_module.complete_json("JSON instruction", {})
    assert "401" in str(raised.value)
    assert "test-secret" not in str(raised.value)
    assert "private payload" not in str(raised.value)
