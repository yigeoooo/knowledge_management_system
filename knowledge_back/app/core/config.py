import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

# ``core/config.py`` is one package deeper than the historical module.  The
# project root remains the parent used for .env files, migrations, and runtime
# state.
ROOT = Path(__file__).resolve().parents[2]


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
    max_document_size = int(overrides.get("MAX_DOCUMENT_SIZE", os.getenv("MAX_DOCUMENT_SIZE", str(200 * 1024 * 1024))))
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
        "MAX_CONTENT_LENGTH": max_document_size,
        "MINIO_ENDPOINT": os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
        "MINIO_PUBLIC_ENDPOINT": os.getenv(
            "MINIO_PUBLIC_ENDPOINT", os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
        ),
        "MINIO_ACCESS_KEY": os.getenv("MINIO_ACCESS_KEY", ""),
        "MINIO_SECRET_KEY": os.getenv("MINIO_SECRET_KEY", ""),
        "MINIO_BUCKET": os.getenv("MINIO_BUCKET", "knowledge-documents"),
        "MINIO_SECURE": os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
        "MINIO_URL_SECONDS": int(os.getenv("MINIO_URL_SECONDS", "600")),
        "MAX_DOCUMENT_SIZE": max_document_size,
        "DOCUMENT_UPLOAD_SECONDS": int(os.getenv("DOCUMENT_UPLOAD_SECONDS", "900")),
        "DEEPSEEK_BASE_URL": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
        "DEEPSEEK_CHAT_MODEL": os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat"),
        "DEEPSEEK_TIMEOUT_SECONDS": int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")),
        "QA_MIN_SIMILARITY": float(os.getenv("QA_MIN_SIMILARITY", "0.3")),
        "QA_RERANK_PROVIDER": os.getenv("QA_RERANK_PROVIDER", "lexical"),
        "RERANK_API_KEY": os.getenv("RERANK_API_KEY", ""),
        "RERANK_MODEL": os.getenv("RERANK_MODEL", ""),
        "RERANK_URL": os.getenv("RERANK_URL", "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"),
        "QA_RERANK_ENABLED": os.getenv("QA_RERANK_ENABLED", "true").lower()
        in {"1", "true", "yes"},
        "LANGCHAIN_CHAT_ENABLED": os.getenv("LANGCHAIN_CHAT_ENABLED", "true").lower() in {"1", "true", "yes"},
        "LANGCHAIN_STRUCTURED_OUTPUT": os.getenv("LANGCHAIN_STRUCTURED_OUTPUT", "true").lower()
        in {"1", "true", "yes"},
        "LANGSMITH_TRACING": os.getenv("LANGSMITH_TRACING", "false").lower()
        in {"1", "true", "yes"},
        "LANGSMITH_CAPTURE_CONTENT": os.getenv("LANGSMITH_CAPTURE_CONTENT", "false").lower() in {"1", "true", "yes"},
        "QA_CONTEXT_TOKEN_BUDGET": max(2000, int(os.getenv("QA_CONTEXT_TOKEN_BUDGET", "12000"))),
        "LANGSMITH_API_KEY": os.getenv("LANGSMITH_API_KEY", ""),
        "LANGSMITH_AGENT_ID": os.getenv("LANGSMITH_AGENT_ID", ""),
        "LANGSMITH_AGENT_ENVIRONMENT": os.getenv("LANGSMITH_AGENT_ENVIRONMENT", "local"),
        "LANGSMITH_PROJECT": os.getenv("LANGSMITH_PROJECT", "knowledge-management-system"),
        "LANGSMITH_ENDPOINT": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        "LANGSMITH_SAMPLING_RATE": float(os.getenv("LANGSMITH_SAMPLING_RATE", "1.0")),
        "EVALUATION_WORKER_AUTOSTART": os.getenv("EVALUATION_WORKER_AUTOSTART", "true").lower() in {"1", "true", "yes"},
        "QA_WORKER_AUTOSTART": os.getenv("QA_WORKER_AUTOSTART", "true").lower() in {"1", "true", "yes"},
        "ROBOT_ANSWER_WAIT_SECONDS": max(1, min(600, int(os.getenv("ROBOT_ANSWER_WAIT_SECONDS", "180")))),
        "QA_LEASE_SECONDS": max(60, int(os.getenv("QA_LEASE_SECONDS", "300"))),
        "QA_MAX_ATTEMPTS": max(1, int(os.getenv("QA_MAX_ATTEMPTS", "3"))),
        "QA_RECENT_TURNS": max(1, min(20, int(os.getenv("QA_RECENT_TURNS", "6")))),
        "QA_HISTORY_BUDGET": max(1000, min(32000, int(os.getenv("QA_HISTORY_BUDGET", "9000")))),
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
