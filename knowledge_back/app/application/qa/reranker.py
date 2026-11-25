"""Deterministic reranking used before an optional model reranker.

This is deliberately provider-free.  It gives the RAG pipeline an explicit
reranker seam today and provides a stable fallback when an external rerank
model is unavailable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class Reranker(Protocol):
    def rank(self, question: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...


def _terms(question: str) -> list[str]:
    text = question.casefold()
    latin = re.findall(r"[a-z0-9][a-z0-9_.-]{1,39}", text)
    chinese = []
    for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(phrase) <= 8:
            chinese.append(phrase)
        chinese.extend(phrase[index : index + 2] for index in range(len(phrase) - 1))
    return list(dict.fromkeys(latin + chinese))[:24]


@dataclass(frozen=True)
class LexicalReranker:
    """Blend semantic score with explainable title/heading/content signals."""

    semantic_weight: float = 0.72
    lexical_weight: float = 0.28

    def rank(self, question: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        terms = _terms(question)
        if not terms:
            return sources
        scored = []
        for position, source in enumerate(sources):
            title = str(source.get("document_title") or "").casefold()
            heading = str(source.get("heading_path") or "").casefold()
            content = str(source.get("content") or "").casefold()
            title_hits = sum(term in title for term in terms)
            heading_hits = sum(term in heading for term in terms)
            content_hits = sum(term in content for term in terms)
            coverage = min(1.0, (title_hits * 3 + heading_hits * 2 + content_hits) / max(1, len(terms) * 3))
            semantic = source.get("score")
            if not isinstance(semantic, (int, float)):
                semantic = 0.0
            # Keep the original order as the final tie-breaker.  This makes the
            # fallback predictable and avoids unstable answers across requests.
            score = self.semantic_weight * float(semantic) + self.lexical_weight * coverage
            scored.append((score, -position, source))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        result = []
        for score, _, source in scored:
            result.append({**source, "rerank_score": round(score, 6)})
        return result


DEFAULT_RERANKER = LexicalReranker()


class DashScopeReranker:
    """Bounded rerank request. An invalid ranking falls back to original RRF order."""
    def rank(self, question, sources):
        import json
        import math
        from urllib.request import Request, urlopen

        from flask import current_app
        config = current_app.config
        key, model = config.get("RERANK_API_KEY", ""), config.get("RERANK_MODEL", "")
        if not key or not model:
            raise ValueError("reranker configuration missing")
        texts = [s for s in sources if s.get("modality") == "text"]
        media = [s for s in sources if s.get("modality") != "text"]
        if not texts:
            return sources
        payload = {"model": model, "input": {"query": question,
                    "documents": [s.get("content") or "" for s in texts]},
                   "parameters": {"top_n": len(texts), "return_documents": False}}
        request = Request(config["RERANK_URL"], data=json.dumps(payload).encode(),
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            body = response.read(1_048_577)
        if len(body) > 1_048_576:
            raise ValueError("reranker response too large")
        rows = json.loads(body)["output"]["results"]
        seen, ranked = set(), []
        for row in rows:
            index, score = row["index"], row["relevance_score"]
            if (type(index) is not int or index in seen or not 0 <= index < len(texts)
                    or not isinstance(score, (int, float)) or not math.isfinite(score)):
                raise ValueError("invalid ranking")
            seen.add(index)
            ranked.append({**texts[index], "rerank_score": float(score)})
        if len(seen) != len(texts):
            raise ValueError("incomplete ranking")
        return sorted(ranked, key=lambda s: s["rerank_score"], reverse=True) + media


def rerank_sources(question, sources, *, enabled=True):
    from flask import current_app
    if not enabled or len(sources) < 2:
        return sources
    provider = current_app.config.get("QA_RERANK_PROVIDER", "lexical")
    if provider == "lexical":
        return DEFAULT_RERANKER.rank(question, sources)
    if provider == "dashscope":
        try:
            return DashScopeReranker().rank(question, sources)
        except (OSError, ValueError, KeyError, TypeError):
            current_app.logger.warning("rag reranker unavailable; keeping RRF order")
            return [{**s, "rerank_fallback": True} for s in sources]
    raise ValueError("未知的重排配置，请选择 lexical 或 dashscope")
