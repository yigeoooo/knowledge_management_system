"""Console diagnostics for HTTP requests, SQL and background exceptions."""

import json
import logging
import re
import traceback
from time import perf_counter
from uuid import uuid4

from flask import g, has_request_context, request
from flask.logging import default_handler
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .http import ApiError

_SENSITIVE = re.compile(
    r"password|passwd|secret|token|authorization|cookie|api.?key|credential", re.IGNORECASE
)
_CREDENTIAL = re.compile(
    r"""(?i)((?:password|passwd|secret|token|api[_-]?key|authorization|cookie)[\w-]*["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;&}\]]+)"""
)


def _scrub(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _SENSITIVE.search(str(key)):
                if has_request_context():
                    values = item if isinstance(item, list) else [item]
                    g.setdefault("log_secrets", set()).update(
                        str(v) for v in values if v is not None and len(str(v)) >= 4
                    )
                result[key] = "[REDACTED]"
            else:
                result[key] = _scrub(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


class DiagnosticFormatter(logging.Formatter):
    def __init__(self, config):
        super().__init__(
            "%(asctime)s.%(msecs)03d %(levelname)-7s [%(threadName)s] "
            "%(name)s [request_id=%(request_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.secrets = {
            str(value)
            for key, value in config.items()
            if _SENSITIVE.search(key) and isinstance(value, str) and len(value) >= 4
        }
        uri = config.get("SQLALCHEMY_DATABASE_URI")
        if getattr(uri, "password", None):
            self.secrets.add(uri.password)

    def formatException(self, exc_info):
        return self._exception(exc_info[1], exc_info[2], set())

    def _exception(self, error, tb, seen):
        if id(error) in seen:
            return ""
        seen.add(id(error))
        prefix = ""
        if not isinstance(error, SQLAlchemyError):
            cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
            if cause is not None:
                prefix = (
                    self._exception(cause, cause.__traceback__, seen)
                    + "\nCaused by / during handling:\n"
                )
        frames = "Traceback (most recent call last):\n" + "".join(traceback.format_tb(tb))
        if isinstance(error, SQLAlchemyError):
            # DBAPI exception strings can include parameter values and PostgreSQL
            # DETAIL / failing rows even when SQLAlchemy hides parameters.
            original = getattr(error, "orig", None)
            diagnostic = getattr(original, "diag", None)
            message = getattr(diagnostic, "message_primary", None)
            if not message:
                message = (str(original or error).splitlines() or [type(error).__name__])[0]
            return (
                frames
                + f"{type(error).__name__}: {message}\n"
                + f"DBAPI={type(original).__name__} SQLSTATE={getattr(original, 'sqlstate', '-')}; "
                "SQL parameters omitted"
            )
        if isinstance(error, ApiError):
            return (
                prefix
                + frames
                + f"ApiError: {error.message} (status={error.status}, code={error.code})"
            )
        return (
            prefix + frames + "".join(traceback.format_exception_only(type(error), error)).rstrip()
        )

    def format(self, record):
        record.request_id = g.get("request_id", "-") if has_request_context() else "-"
        # Format a copy so the sanitized traceback is not cached on records used
        # by other handlers or applications.
        record = logging.makeLogRecord(record.__dict__)
        record.exc_text = None
        text = super().format(record)
        secrets = self.secrets | (g.get("log_secrets", set()) if has_request_context() else set())
        for secret in sorted(secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
        text = re.sub(r"(://[^\s/:]+:)[^\s@]+@", r"\1[REDACTED]@", text)
        return _CREDENTIAL.sub(r"\1[REDACTED]", text)


def configure_logging(app):
    level = app.config["LOG_LEVEL"].upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    root = logging.getLogger()
    # Flask reloads and test factories may configure logging repeatedly.
    for handler in root.handlers[:]:
        if getattr(handler, "_kbs_console", False):
            root.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler()
    handler._kbs_console = True
    handler.setLevel(level)
    handler.setFormatter(DiagnosticFormatter(app.config))
    root.addHandler(handler)
    root.setLevel(level)
    app.logger.removeHandler(default_handler)
    app.logger.setLevel(level)
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and (
            name == app.name or name.startswith(app.name + ".")
        ):
            logger.disabled = False
    # Our access log includes timing and safe query parameters, replacing the
    # duplicate Werkzeug access line (which otherwise prints raw query strings).
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    app.extensions["diagnostic_formatter"] = handler.formatter

    limit = app.config["LOG_MAX_BODY_BYTES"]

    def serialize(value):
        text = json.dumps(_scrub(value), ensure_ascii=False, default=str)
        return text if len(text) <= limit else text[:limit] + "…[truncated]"

    @app.before_request
    def log_request():
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = (
            supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", supplied) else str(uuid4())
        )
        g.request_started = perf_counter()
        # Remember credentials for scrubbing later exception messages; headers
        # themselves are deliberately not printed on every request.
        _scrub(dict(request.headers))
        payload = None
        try:
            if request.mimetype == "multipart/form-data":
                payload = "[multipart: file metadata logged after parsing]"
            elif request.content_length and request.content_length > limit:
                payload = f"[body omitted: {request.content_length} bytes, limit={limit}]"
            elif request.content_length:
                if request.is_json:
                    payload = request.get_json(silent=True)
                    if payload is None:
                        payload = "[invalid JSON; raw body omitted]"
                elif request.mimetype == "application/x-www-form-urlencoded":
                    payload = request.form.to_dict(flat=False)
                else:
                    payload = f"[body type={request.mimetype}; raw body omitted]"
        except Exception as error:  # noqa: BLE001 - logging must not change request parsing errors
            payload = f"[body unavailable: {type(error).__name__}]"
        app.logger.info(
            "HTTP -> %s %s query=%s body=%s",
            request.method,
            request.path,
            serialize(request.args.to_dict(flat=False)),
            serialize(payload),
        )

    @app.after_request
    def log_response(response):
        if request.mimetype == "multipart/form-data":
            # Use only what the endpoint already parsed; never consume upload
            # streams or read a binary download just for logging.
            form, files = request.__dict__.get("form"), request.__dict__.get("files")
            app.logger.info(
                "HTTP multipart form=%s files=%s",
                serialize(form.to_dict(flat=False) if form else {}),
                serialize(
                    [
                        {
                            "field": key,
                            "filename": value.filename,
                            "type": value.mimetype,
                            "size": value.content_length or None,
                        }
                        for key, value in files.items(multi=True)
                    ]
                    if files
                    else []
                ),
            )
        elapsed = (perf_counter() - g.get("request_started", perf_counter())) * 1000
        level = (
            logging.ERROR
            if response.status_code >= 500
            else logging.WARNING
            if response.status_code >= 400
            else logging.INFO
        )
        app.logger.log(
            level,
            "HTTP <- %s %s status=%s duration=%.2fms",
            request.method,
            request.path,
            response.status_code,
            elapsed,
        )
        return response


def configure_sql_logging(app):
    logger = logging.getLogger("app.sql")
    with app.app_context():
        engines = list(db.engines.values())
    for engine in engines:
        # Prevent accidental echo/debug logging of passwords, embeddings and
        # document contents through SQL bind parameters.
        engine.hide_parameters = True
        engine.echo = False

        @event.listens_for(engine, "before_cursor_execute")
        def before_sql(conn, cursor, statement, parameters, context, executemany):
            context._kbs_started = perf_counter()

        def write_sql(context, statement, *, failed=False, rows=None):
            elapsed = (perf_counter() - getattr(context, "_kbs_started", perf_counter())) * 1000
            slow = elapsed >= app.config["LOG_SQL_SLOW_MS"]
            if not (app.config["LOG_SQL_ENABLED"] or slow or failed):
                return
            sql = " ".join((statement or "[connection failed before SQL]").split())
            limit = app.config["LOG_MAX_BODY_BYTES"]
            sql = sql if len(sql) <= limit else sql[:limit] + "…[truncated]"
            logger.log(
                logging.ERROR if failed else logging.WARNING if slow else logging.INFO,
                "SQL%s duration=%.2fms rows=%s statement=%s",
                " FAILED" if failed else " SLOW" if slow else "",
                elapsed,
                rows,
                sql,
            )

        @event.listens_for(engine, "after_cursor_execute")
        def after_sql(conn, cursor, statement, parameters, context, executemany):
            write_sql(context, statement, rows=cursor.rowcount)

        @event.listens_for(engine, "handle_error")
        def sql_error(context):
            write_sql(context.execution_context, context.statement, failed=True)
            error = context.sqlalchemy_exception or context.original_exception
            logger.error(
                "Database execution failed", exc_info=(type(error), error, error.__traceback__)
            )
