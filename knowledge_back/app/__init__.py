from flask import Flask, g, jsonify
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from .core.config import ROOT, configuration
from .core.extensions import db, limiter, migrate
from .core.http import ApiError, success
from .core.logging import configure_logging, configure_sql_logging
from .integrations.ai.langsmith_config import configure_langsmith


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(configuration(overrides or {}))
    configure_logging(app)
    app.extensions["langsmith"] = configure_langsmith(app.config)
    app.config["LANGSMITH_CONFIGURED"] = app.extensions["langsmith"] is not None
    db.init_app(app)
    configure_sql_logging(app)
    migrate.init_app(app, db, directory=str(ROOT / "migrations"))
    limiter.init_app(app)

    from .api.register import register_blueprints
    from .cli import register_cli

    register_blueprints(app)
    register_cli(app)

    @app.after_request
    def response_headers(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def error_response(error):
        return jsonify(
            code=error.code, message=error.message, data=None, request_id=g.get("request_id", "")
        ), error.status

    @app.errorhandler(ApiError)
    def api_error(error):
        log = app.logger.error if error.status >= 500 else app.logger.warning
        log("API error status=%s code=%s message=%s", error.status, error.code, error.message,
            exc_info=error.status >= 500)
        return error_response(error)

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = "请求过于频繁，请稍后再试" if error.code == 429 else error.description
        app.logger.warning("HTTP error status=%s type=%s message=%s", error.code, type(error).__name__, message)
        return error_response(ApiError(message, error.code, error.code * 100))

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        app.logger.exception("Database request failed type=%s", type(error).__name__)
        db.session.rollback()
        return error_response(ApiError("数据服务暂不可用，请稍后重试", 503, 50301))

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Unhandled request exception type=%s", type(error).__name__)
        db.session.rollback()
        return error_response(ApiError("服务内部异常，请稍后重试", 500, 50000))

    @app.get("/api/v1/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return success({"status": "ok", "database": "ok"})

    return app
