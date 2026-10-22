import importlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
            "JWT_SECRET_KEY": "test-only-secret-never-used-in-production",
            "RATELIMIT_ENABLED": False,
            "SESSION_COOKIE_SECURE": False,
        }
    )
    # The knowledge-base API now provisions a MinIO bucket.  Keep this
    # database-only fixture deterministic; the integration environment covers
    # the real object-storage call.
    workspace_module = importlib.import_module("app.workspace")
    monkeypatch.setattr(workspace_module, "ensure_bucket", lambda bucket: bucket)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    # Test-only SQLite adapter: use the actual init.sql seed data, not a parallel Python seeder.
    seed_sql = (
        (Path(__file__).resolve().parents[2] / "init.sql").read_text().split("-- 初始角色", 1)[1]
    )
    with app.app_context():
        connection = db.session.connection().connection.driver_connection
        connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)
        connection.create_function("now", 0, lambda: datetime.now(UTC).isoformat())
        connection.executescript("BEGIN;\n" + seed_sql.replace("::json", ""))
    result = runner.invoke(
        args=["create-user", "--username", "admin", "--role", "super_admin"],
        input="Test-Password-2026!\nTest-Password-2026!\n",
    )
    assert result.exit_code == 0, result.output
    return app


@pytest.fixture
def client(app):
    return app.test_client()
