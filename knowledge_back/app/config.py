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
        "MAX_CONTENT_LENGTH": int(os.getenv("MAX_DOCUMENT_SIZE", str(20 * 1024 * 1024))),
        "MINIO_ENDPOINT": os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
        "MINIO_PUBLIC_ENDPOINT": os.getenv(
            "MINIO_PUBLIC_ENDPOINT", os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
        ),
        "MINIO_ACCESS_KEY": os.getenv("MINIO_ACCESS_KEY", ""),
        "MINIO_SECRET_KEY": os.getenv("MINIO_SECRET_KEY", ""),
        "MINIO_BUCKET": os.getenv("MINIO_BUCKET", "knowledge-documents"),
        "MINIO_SECURE": os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
        "MINIO_URL_SECONDS": int(os.getenv("MINIO_URL_SECONDS", "600")),
        "MAX_DOCUMENT_SIZE": int(os.getenv("MAX_DOCUMENT_SIZE", str(20 * 1024 * 1024))),
        "DOCUMENT_UPLOAD_SECONDS": int(os.getenv("DOCUMENT_UPLOAD_SECONDS", "900")),
        "DASHSCOPE_BASE_URL": os.getenv("DASHSCOPE_BASE_URL", ""),
        "DASHSCOPE_API_KEY": os.getenv("DASHSCOPE_API_KEY", ""),
        "DASHSCOPE_EMBEDDING_MODEL": os.getenv("DASHSCOPE_EMBEDDING_MODEL", ""),
        "DASHSCOPE_EMBEDDING_URL": os.getenv("DASHSCOPE_EMBEDDING_URL", ""),
        "DASHSCOPE_EMBEDDING_MODE": os.getenv("DASHSCOPE_EMBEDDING_MODE", "text"),
        "DASHSCOPE_EMBEDDING_DIMENSION": os.getenv("DASHSCOPE_EMBEDDING_DIMENSION", ""),
        "DASHSCOPE_EMBEDDING_MAX_VIDEO_FRAMES": int(
            os.getenv("DASHSCOPE_EMBEDDING_MAX_VIDEO_FRAMES", "16")
        ),
        "EMBEDDING_PROVIDER": os.getenv("EMBEDDING_PROVIDER", "dashscope"),
        "INDEX_WORKER_BATCH_SIZE": int(os.getenv("INDEX_WORKER_BATCH_SIZE", "1")),
        "INDEX_WORKER_AUTOSTART": os.getenv("INDEX_WORKER_AUTOSTART", "true").lower()
        in {"1", "true", "yes"},
        "RATELIMIT_STORAGE_URI": os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        **overrides,
    }
