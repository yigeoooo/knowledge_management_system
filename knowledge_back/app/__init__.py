import re
from uuid import uuid4

from flask import Flask, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from .config import ROOT, configuration
from .extensions import db, limiter, migrate
from .http import ApiError, success


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(configuration(overrides or {}))
    db.init_app(app)
    migrate.init_app(app, db, directory=str(ROOT / "migrations"))
    limiter.init_app(app)

    from .auth import auth
    from .cli import register_cli
    from .roles import roles
    from .users import users
    from .workspace import workspace

    app.register_blueprint(auth)
    app.register_blueprint(roles)
    app.register_blueprint(workspace)
    app.register_blueprint(users)
    register_cli(app)

    @app.before_request
    def request_context():
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = (
            supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", supplied) else str(uuid4())
        )

    @app.after_request
    def response_headers(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(
            code=error.code, message=error.message, data=None, request_id=g.get("request_id", "")
        ), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = "请求过于频繁，请稍后再试" if error.code == 429 else error.description
        return api_error(ApiError(message, error.code, error.code * 100))

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error(
            "Database operation failed request_id=%s type=%s",
            g.get("request_id"),
            type(error).__name__,
        )
        return api_error(ApiError("数据服务暂不可用，请稍后重试", 503, 50301))

    @app.get("/api/v1/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return success({"status": "ok", "database": "ok"})

    return app
