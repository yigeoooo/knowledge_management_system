"""Versioned metadata describing how a document was indexed."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from flask import current_app

INDEX_PROFILE_VERSION = "rag-index-v2"
PARSER_VERSION = "parser-v3"
CHUNK_STRATEGY = "langchain-section-blocks"


def build_index_profile(*, embedding_model: str, dimension: int | None = None) -> dict[str, Any]:
    return {
        "profile_version": INDEX_PROFILE_VERSION,
        "parser_version": PARSER_VERSION,
        "chunk_strategy": CHUNK_STRATEGY,
        "chunk_size": 1600,
        "chunk_overlap": 160,
        "embedding_model": embedding_model,
        "embedding_dimension": dimension,
        "metadata_schema": "chunk-metadata-v1",
        "normalization": "processor-normalized",
    }


def profile_hash(profile: dict[str, Any]) -> str:
    payload = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def configured_profile(embedding_model: str, dimension: int | None = None) -> dict[str, Any]:
    """Return the profile used by the current deployment for diagnostics."""

    profile = build_index_profile(embedding_model=embedding_model, dimension=dimension)
    profile["embedding_provider"] = current_app.config.get("EMBEDDING_PROVIDER", "dashscope")
    return profile


__all__ = [
    "CHUNK_STRATEGY",
    "INDEX_PROFILE_VERSION",
    "PARSER_VERSION",
    "build_index_profile",
    "configured_profile",
    "profile_hash",
]
