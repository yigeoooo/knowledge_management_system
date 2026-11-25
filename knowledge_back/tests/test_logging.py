import io
import logging
from types import SimpleNamespace

import pytest
from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.core.extensions import db
from app.core.http import ApiError
from app.integrations.ai.chat_adapter import ChatError
from app.workers import evaluation_worker


@pytest.fixture
def diagnostics(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'logs.db'}",
            "JWT_SECRET_KEY": "logging-test-secret-not-for-production",
            "LANGSMITH_TRACING": False,
            "RATELIMIT_ENABLED": False,
            "LOG_LEVEL": "INFO",
            "LOG_SQL_ENABLED": True,
            "LOG_SQL_SLOW_MS": 500,
            "LOG_MAX_BODY_BYTES": 1024,
        }
    )
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(app.extensions["diagnostic_formatter"])
    logging.getLogger().addHandler(handler)

    @app.post("/diagnostic/echo")
    def echo():
        return jsonify(request.get_json())

    @app.post("/diagnostic/form")
    def form():
        uploads = [f.read().decode() for f in request.files.values()]
        return jsonify(form=request.form.to_dict(flat=False), uploads=uploads)

    @app.get("/diagnostic/sql")
    def sql():
        value = db.session.execute(db.text("SELECT :value"), {"value": "private-sql-bind"}).scalar()
        return jsonify(value=value)

    @app.get("/diagnostic/sql-error")
    def sql_error():
        db.session.execute(
            db.text("SELECT * FROM missing_table WHERE password=:password"),
            {"password": "private-database-parameter"},
        )

    @app.post("/diagnostic/error")
    def error():
        payload = request.get_json()
        raise ValueError("invalid test value " + payload["password"])

    @app.get("/diagnostic/api-error")
    def api_error():
        raise ApiError("测试题不存在", 404, 40401)

    yield app, app.test_client(), output
    logging.getLogger().removeHandler(handler)
    handler.close()
    with app.app_context():
        db.engine.dispose()


def test_request_logs_parameters_timing_and_request_id_without_exposing_credentials(diagnostics):
    _, client, output = diagnostics
    body = {
        "question": "8个人要多少钱？",
        "password": "private-password",
        "nested": [{"apiKey": "private-api-key", "keep": "可见参数"}],
    }
    response = client.post(
        "/diagnostic/echo?tag=one&tag=two&token=private-query-token",
        json=body,
        headers={"Authorization": "Bearer private-access-token", "X-Request-ID": "log-test-123"},
    )
    assert response.status_code == 200 and response.json == body
    assert response.headers["X-Request-ID"] == "log-test-123"
    text = output.getvalue()
    assert "HTTP -> POST /diagnostic/echo" in text and "8个人要多少钱？" in text
    assert '"tag": ["one", "two"]' in text and "可见参数" in text
    assert "HTTP <- POST /diagnostic/echo status=200 duration=" in text
    assert "[request_id=log-test-123]" in text and "[REDACTED]" in text
    assert "private-" not in text


def test_form_and_upload_logging_does_not_consume_files(diagnostics):
    _, client, output = diagnostics
    response = client.post(
        "/diagnostic/form", data={"title": "表单参数", "password": "private-form-password"}
    )
    assert response.status_code == 200 and response.json["form"]["title"] == ["表单参数"]
    assert "表单参数" in output.getvalue() and "private-form-password" not in output.getvalue()
    response = client.post(
        "/diagnostic/form",
        data={
            "title": "上传标题",
            "secret": "private-upload-secret",
            "document": (io.BytesIO(b"private-file-contents"), "sample.txt"),
        },
    )
    assert response.status_code == 200 and response.json["uploads"] == ["private-file-contents"]
    text = output.getvalue()
    assert "HTTP multipart" in text and "sample.txt" in text and "上传标题" in text
    assert "private-upload-secret" not in text and "private-file-contents" not in text


def test_sql_is_timed_and_bound_values_are_hidden(diagnostics):
    app, client, output = diagnostics
    response = client.get("/diagnostic/sql", headers={"X-Request-ID": "sql-request"})
    assert response.status_code == 200 and response.json["value"] == "private-sql-bind"
    text = output.getvalue()
    assert "SQL duration=" in text and "statement=SELECT ?" in text
    assert "[request_id=sql-request]" in text and "private-sql-bind" not in text
    app.config["LOG_SQL_ENABLED"] = False
    output.seek(0)
    output.truncate()
    client.get("/diagnostic/sql")
    assert "statement=SELECT" not in output.getvalue()
    app.config["LOG_SQL_SLOW_MS"] = 0
    client.get("/diagnostic/sql")
    assert "SQL SLOW" in output.getvalue()


def test_database_error_has_sql_type_and_stack_but_response_stays_safe(diagnostics):
    app, client, output = diagnostics
    app.config["LOG_SQL_ENABLED"] = False
    response = client.get("/diagnostic/sql-error")
    assert response.status_code == 503 and response.json["code"] == 50301
    assert response.json["message"] == "数据服务暂不可用，请稍后重试"
    text = output.getvalue()
    assert "SQL FAILED" in text and "missing_table" in text
    assert "OperationalError" in text and "Traceback (most recent call last)" in text
    assert "test_logging.py" in text and "private-database-parameter" not in text


def test_unexpected_error_logs_stack_and_redacts_request_password(diagnostics):
    _, client, output = diagnostics
    response = client.post("/diagnostic/error", json={"password": "private-exception-password"})
    assert response.status_code == 500 and response.json["code"] == 50000
    assert response.headers["X-Request-ID"] == response.json["request_id"]
    text = output.getvalue()
    assert "ValueError: invalid test value" in text and "test_logging.py" in text
    assert "Traceback (most recent call last)" in text and "status=500" in text
    assert "private-exception-password" not in text
    assert "ValueError" not in response.get_data(as_text=True)


def test_expected_errors_and_invalid_or_large_bodies_keep_original_behavior(diagnostics):
    _, client, output = diagnostics
    response = client.get("/diagnostic/api-error")
    assert response.status_code == 404 and response.json["code"] == 40401
    assert "测试题不存在" in output.getvalue() and "Traceback" not in output.getvalue()
    response = client.post(
        "/diagnostic/echo", data='{"password": invalid', content_type="application/json"
    )
    assert response.status_code == 400 and "[invalid JSON" in output.getvalue()
    body = {"question": "oversized-private-content" * 100}
    response = client.post(
        "/diagnostic/echo", json=body, headers={"X-Request-ID": "invalid request id"}
    )
    assert response.status_code == 200 and response.json == body
    assert response.headers["X-Request-ID"] != "invalid request id"
    assert (
        "[body omitted:" in output.getvalue()
        and "oversized-private-content" not in output.getvalue()
    )


def test_wrapped_database_errors_do_not_leak_postgres_details_or_parameters(diagnostics):
    app, _, output = diagnostics
    original = RuntimeError("duplicate key\nDETAIL: Key (password)=(private-postgres-value)")
    original.diag = SimpleNamespace(message_primary="duplicate key violates unique constraint")
    parameters = ["private-parameter"]
    try:
        try:
            raise IntegrityError("INSERT INTO users VALUES (?)", parameters, original)
        except IntegrityError as error:
            raise ApiError("数据冲突", 503) from error
    except ApiError:
        app.logger.exception("wrapped database failure")
    text = output.getvalue()
    assert "IntegrityError" in text and "duplicate key violates unique constraint" in text
    assert "private-" not in text and "ApiError: 数据冲突" in text


def test_background_evaluation_failures_include_context_and_stack(diagnostics, monkeypatch):
    app, _, output = diagnostics

    def fail(*args, **kwargs):
        raise ChatError("问答模型连接超时，请稍后重试")

    monkeypatch.setattr(evaluation_worker, "evaluate_input", fail)
    with app.app_context():
        result = evaluation_worker.evaluate_arm(
            {"inputs": {}, "reference": {}},
            {},
            {
                "evaluation_run_id": "run-123",
                "evaluation_example_id": "question-456",
                "evaluation_arm": "candidate",
            },
        )
    assert result["error"] == "ChatError"
    text = output.getvalue()
    assert "evaluation arm failed" in text and "run-123" in text and "question-456" in text
    assert "candidate" in text and "ChatError: 问答模型连接超时" in text and "Traceback" in text


def test_migrations_preserve_application_request_and_sql_logging(diagnostics):
    app, client, output = diagnostics
    result = app.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    output.seek(0)
    output.truncate()
    assert client.get("/api/v1/health").status_code == 200
    text = output.getvalue()
    assert "HTTP -> GET /api/v1/health" in text and "statement=SELECT 1" in text
    assert sum(getattr(h, "_kbs_console", False) for h in logging.getLogger().handlers) == 1
