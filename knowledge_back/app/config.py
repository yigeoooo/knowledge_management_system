import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]


def configuration(overrides):
    load_dotenv(ROOT / ".env.local")
    production = os.getenv("APP_ENV", "local") != "local"
    secret = overrides.get("JWT_SECRET_KEY") or os.getenv("JWT_SECRET_KEY")
    if not secret:
        if production:
            raise RuntimeError("JWT_SECRET_KEY must be configured outside local development")
        directory = ROOT / ".runtime"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / "jwt-secret"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_hex(32))
        secret = path.read_text().strip()
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 characters")
    return {
        "SQLALCHEMY_DATABASE_URI": URL.create(
            "postgresql+psycopg",
            username=os.getenv("POSTGRES_USER", "root"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "knowledge_db"),
        ),
        "JWT_SECRET_KEY": secret,
        "ACCESS_TOKEN_SECONDS": 900,
        "REFRESH_TOKEN_DAYS": 7,
        "SESSION_COOKIE_SECURE": production,
        "MAX_CONTENT_LENGTH": 16384,
        "RATELIMIT_STORAGE_URI": os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        **overrides,
    }
