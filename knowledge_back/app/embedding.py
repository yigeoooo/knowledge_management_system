"""DashScope text and multimodal Embedding adapter.

DashScope's multimodal Embedding models expose one shared vector space for
text, images and videos. The caller supplies one item per vector, for example
``{"text": "..."}``, ``{"image": "https://..."}`` or
``{"video": "https://..."}``.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class EmbeddingError(RuntimeError):
    """Embedding configuration or provider failure."""


def _url(mode: str) -> str:
    configured = current_app.config.get("DASHSCOPE_EMBEDDING_URL", "").strip()
    if configured:
        return configured
    base = current_app.config.get("DASHSCOPE_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise EmbeddingError("未配置 DashScope Embedding 服务")
    if mode == "multimodal":
        return f"{base}/services/embeddings/multimodal-embedding/multimodal-embedding"
    if mode in {"openai", "openai-compatible"}:
        return f"{base}/embeddings"
    return f"{base}/services/embeddings/text-embedding/text-embedding"


def _configuration() -> tuple[str, str, str]:
    provider = current_app.config.get("EMBEDDING_PROVIDER", "dashscope").lower()
    model = current_app.config.get("DASHSCOPE_EMBEDDING_MODEL", "").strip()
    api_key = current_app.config.get("DASHSCOPE_API_KEY", "").strip()
    mode = current_app.config.get("DASHSCOPE_EMBEDDING_MODE", "text").lower()
    if provider != "dashscope" or not model or not api_key:
        raise EmbeddingError("Embedding 服务未配置，无法建立文档索引")
    return model, api_key, mode


def _parameters() -> dict:
    parameters = {"output_type": "dense"}
    configured_dimension = current_app.config.get("DASHSCOPE_EMBEDDING_DIMENSION", "")
    if configured_dimension:
        try:
            parameters["dimension"] = int(configured_dimension)
        except (TypeError, ValueError) as error:
            raise EmbeddingError("Embedding 向量维度配置不正确") from error
    if current_app.config.get("DASHSCOPE_EMBEDDING_MODE", "").lower() == "multimodal":
        max_video_frames = current_app.config.get("DASHSCOPE_EMBEDDING_MAX_VIDEO_FRAMES")
        if max_video_frames:
            parameters["max_video_frames"] = int(max_video_frames)
    return parameters


def _parse_vectors(payload, expected_count: int) -> list[list[float]]:
    values = payload.get("data") if isinstance(payload, dict) else None
    if values is None and isinstance(payload, dict):
        output = payload.get("output")
        if isinstance(output, dict):
            values = output.get("embeddings")
            if not values and output.get("embedding"):
                values = [{"index": 0, "embedding": output["embedding"]}]
    if not isinstance(values, list):
        raise EmbeddingError("Embedding 服务响应格式不正确")
    try:
        def index_of(value):
            if isinstance(value, dict):
                return int(value.get("index", value.get("text_index", 0)))
            return 0

        ordered = sorted(values, key=index_of)
        vectors = [value if isinstance(value, list) else value["embedding"] for value in ordered]
        if len(vectors) != expected_count or any(
            not isinstance(vector, list)
            or not vector
            or any(not isinstance(item, (int, float)) for item in vector)
            for vector in vectors
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise EmbeddingError("Embedding 服务返回的向量格式不正确") from error
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise EmbeddingError("Embedding 服务返回了不一致的向量维度")
    configured_dimension = current_app.config.get("DASHSCOPE_EMBEDDING_DIMENSION", "")
    if configured_dimension and len(vectors[0]) != int(configured_dimension):
        raise EmbeddingError("Embedding 向量维度与配置不一致")
    return vectors


def _request(payload: dict, *, mode: str, expected_count: int) -> tuple[list[list[float]], str]:
    model, api_key, _ = _configuration()
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        _url(mode),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        raise EmbeddingError(f"Embedding 服务返回 HTTP {error.code}") from error
    except (URLError, TimeoutError, ValueError) as error:
        raise EmbeddingError("Embedding 服务暂时不可用") from error
    return _parse_vectors(result, expected_count), model


def embed_contents(contents: list[dict[str, str]]) -> tuple[list[list[float]], str]:
    """Embed text/image/video content in DashScope's shared vector space."""

    if not contents:
        model, _, _ = _configuration()
        return [], model
    model, _, mode = _configuration()
    if mode != "multimodal":
        raise EmbeddingError(
            "图片和视频需要将 DASHSCOPE_EMBEDDING_MODE 配置为 multimodal，并使用多模态 Embedding 模型"
        )
    if any(set(item) not in ({"text"}, {"image"}, {"video"}) for item in contents):
        raise EmbeddingError("多模态 Embedding 输入必须是 text、image 或 video")
    return _request(
        {"model": model, "input": {"contents": contents}, "parameters": _parameters()},
        mode=mode,
        expected_count=len(contents),
    )


def embed_texts(texts: list[str]) -> tuple[list[list[float]], str]:
    """Embed text chunks using the configured text or multimodal model."""

    if not texts:
        model, _, _ = _configuration()
        return [], model
    model, _, mode = _configuration()
    if mode == "multimodal":
        return embed_contents([{"text": text} for text in texts])
    if mode in {"openai", "openai-compatible"}:
        payload = {"model": model, "input": texts, "parameters": _parameters()}
    else:
        payload = {"model": model, "input": {"texts": texts}, "parameters": _parameters()}
    return _request(payload, mode=mode, expected_count=len(texts))


def embed_query(text: str) -> tuple[list[float], str]:
    """Embed a text query in exactly the same space as indexed content."""

    vectors, model = embed_texts([text])
    if len(vectors) != 1:
        raise EmbeddingError("Embedding 服务没有返回查询向量")
    return vectors[0], model
