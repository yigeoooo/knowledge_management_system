"""Question-aware retrieval: semantic/lexical search, section coverage and neighbours."""

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from flask import current_app
from sqlalchemy import case, func, or_
from sqlalchemy.orm import defer

from ...core.extensions import db
from ...core.http import ApiError
from ...entities import Document, DocumentChunk, DocumentVersion
from ...integrations.ai.embedding_adapter import EmbeddingError
from .reranker import rerank_sources
from .search_service import available_chunks, source_from_row
from .search_service import search_sources as default_search_sources

logger = logging.getLogger(__name__)
STOP_WORDS = (
    "帮我",
    "能不能",
    "可以",
    "这份",
    "这篇",
    "所有",
    "全部",
    "这些",
    "哪些",
    "讲了",
    "讲述",
    "这个知识库",
    "当前知识库",
    "知识库",
    "这些文档",
    "这个文档",
    "文档",
    "这个里面",
    "里面",
    "这个",
    "这里",
    "一下",
    "一些",
    "大概",
    "主要",
    "请问",
    "请",
    "介绍",
    "总结",
    "概括",
    "概览",
    "概述",
    "包含",
    "包括",
    "有哪些",
    "有什么",
    "内容",
    "资料",
    "什么",
    "如何",
    "怎样",
    "怎么样",
    "怎么",
    "使用流程",
    "操作流程",
    "工作流程",
    "使用方法",
    "流程",
    "步骤",
    "使用",
    "的",
    "是",
    "了",
    "吗",
    "呢",
    "和",
    "以及",
    "或者",
    "还是",
    "会",
    "需要",
)


@dataclass
class AnswerMaterial:
    context: list
    media: list
    scope: dict
    retrieval_count: int


def _terms(question):
    text = question.casefold()
    for word in sorted(STOP_WORDS, key=len, reverse=True):
        text = text.replace(word, " ")
    latin = re.findall(r"[a-z0-9][a-z0-9_.-]{1,39}", text)
    chinese = []
    for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(phrase) <= 8:
            chinese.append(phrase)
        chinese.extend(phrase[index : index + 2] for index in range(len(phrase) - 1))
    return list(dict.fromkeys(latin + chinese))[:16]


def question_mode(question):
    if re.search(r"流程|步骤|怎么用|如何使用|怎样使用|使用方法|操作方法|从.*到.*", question):
        return "workflow"
    if re.search(r"概览|概述|概括|总结|介绍|讲了|包含|包括|有哪些|有什么|什么内容", question):
        return "overview"
    return "specific"


def _query(base_id):
    return available_chunks(base_id, current_app.config["DASHSCOPE_EMBEDDING_MODEL"].strip())


def _text_query(base_id):
    return _query(base_id).where(
        func.coalesce(DocumentChunk.chunk_metadata["modality"].as_string(), "text") == "text",
        func.length(func.trim(DocumentChunk.content)) > 0,
    )


def _rows(query):
    return db.session.execute(query.options(defer(DocumentChunk.embedding))).all()


def _anchor(base_id, chunk_id):
    if not chunk_id:
        return []
    rows = _rows(_text_query(base_id).where(DocumentChunk.id == UUID(chunk_id)))
    if not rows:
        raise ApiError("推荐问题的资料已更新，请刷新推荐或重新输入问题", 409, 40903)
    return [source_from_row(*rows[0])]


def _lexical(base_id, terms):
    if not terms:
        return []
    weights = []
    title = func.lower(Document.title)
    compact_title = func.replace(func.replace(func.replace(title, " ", ""), "-", ""), "_", "")
    for term in terms:
        weights.extend(
            [
                case(
                    (
                        or_(
                            title.contains(term, autoescape=True),
                            compact_title.contains(term, autoescape=True),
                        ),
                        6,
                    ),
                    else_=0,
                ),
                case(
                    (func.lower(DocumentChunk.heading_path).contains(term, autoescape=True), 3),
                    else_=0,
                ),
                case(
                    (func.lower(DocumentChunk.content).contains(term, autoescape=True), 1), else_=0
                ),
            ]
        )
    rank = sum(weights)
    rows = _rows(
        _text_query(base_id).where(rank > 0).order_by(rank.desc(), DocumentChunk.id).limit(24)
    )
    return [source_from_row(*row) for row in rows]


def _sections(base_id, version_id, limit=6):
    query = _text_query(base_id).where(DocumentVersion.id == UUID(version_id))
    metadata = db.session.execute(
        query.with_only_columns(
            DocumentChunk.id,
            DocumentChunk.chunk_index,
            DocumentChunk.heading_path,
        )
        .order_by(DocumentChunk.chunk_index)
        .limit(256)
    ).all()
    if not metadata:
        return []
    headings, representatives = set(), []
    for row in metadata:
        if row.heading_path and row.heading_path not in headings:
            headings.add(row.heading_path)
            representatives.append(row)
    if len(representatives) < min(limit, len(metadata)):
        for index in range(min(limit, len(metadata))):
            row = metadata[
                round(index * (len(metadata) - 1) / max(1, min(limit, len(metadata)) - 1))
            ]
            if row not in representatives:
                representatives.append(row)
    if len(representatives) > limit:
        representatives = [
            representatives[round(i * (len(representatives) - 1) / (limit - 1))]
            for i in range(limit)
        ]
    ids = [row.id for row in representatives]
    by_id = {
        str(row[0].id): source_from_row(*row)
        for row in _rows(query.where(DocumentChunk.id.in_(ids)))
    }
    if len(by_id) != len(ids):
        raise ApiError("知识库文档已更新，请重新提问", 409, 40903)
    return [by_id[str(key)] for key in ids]


def _neighbours(base_id, seeds):
    if not seeds:
        return []
    selected = db.session.execute(
        _text_query(base_id)
        .with_only_columns(
            DocumentChunk.document_version_id,
            DocumentChunk.chunk_index,
            DocumentChunk.chunk_metadata["section_id"].as_string(),
        )
        .where(DocumentChunk.id.in_([UUID(s["chunk_id"]) for s in seeds]))
    ).all()
    conditions = [
        (DocumentChunk.document_version_id == version_id)
        & (or_(DocumentChunk.chunk_index.between(index - 1, index + 1),
               (DocumentChunk.chunk_metadata["section_id"].as_string() == section_id)
               & DocumentChunk.chunk_index.between(index - 3, index + 3))
           if section_id else DocumentChunk.chunk_index.between(index - 1, index + 1))
        for version_id, index, section_id in selected
    ]
    rows = (
        _rows(
            _text_query(base_id)
            .where(or_(*conditions))
            .order_by(
                DocumentChunk.document_version_id,
                DocumentChunk.chunk_index,
            )
            .limit(24)
        )
        if conditions
        else []
    )
    return [source_from_row(*row) for row in rows]


def _merge_ranked(vector, lexical):
    values, ranks = {}, {}
    threshold = current_app.config["QA_MIN_SIMILARITY"]
    for group in (vector, lexical):
        for rank, source in enumerate(group, 1):
            if group is vector and (source["score"] or 0) < threshold:
                continue
            key = source["chunk_id"]
            # Preserve measured similarity if the same hit is also lexical.
            values.setdefault(key, source)
            ranks[key] = ranks.get(key, 0) + 1 / (60 + rank)
    return [values[key] for key in sorted(ranks, key=lambda key: ranks[key], reverse=True)]


def _context(candidates):
    from langchain_core.messages.utils import count_tokens_approximately
    chosen, ids, texts = [], set(), set()
    budget = current_app.config.get("QA_CONTEXT_TOKEN_BUDGET", 12000)
    for source in candidates:
        if source["modality"] != "text" or not source["content"] or source["chunk_id"] in ids:
            continue
        content = source["content"].strip()
        key = re.sub(r"\s+", "", content)
        cost = count_tokens_approximately([("human", content)], chars_per_token=1.0)
        if not key or key in texts or cost > budget:
            continue
        # Indexed chunks already have a bound. Do not truncate a command/code block
        # again at an arbitrary 3,000-character boundary.
        ids.add(source["chunk_id"])
        texts.add(key)
        budget -= cost
        chosen.append({**source, "source_id": str(len(chosen) + 1), "content": content})
        if len(chosen) == 10:
            break
    return chosen


def _recall(state):
    base_id, question, anchor_id = state["base_id"], state["question"], state.get("anchor_id")
    mode, terms = question_mode(question), _terms(question)
    anchors = _anchor(base_id, anchor_id)
    scope = {"mode": mode, "coverage": "retrieved_sections"}
    if mode == "overview" and not terms and not anchors:
        versions = (_text_query(base_id).with_only_columns(
            DocumentVersion.id.label("version_id"), Document.title.label("title")
        ).distinct().subquery())
        total = db.session.scalar(db.select(func.count()).select_from(versions))
        entries = db.session.execute(db.select(versions).order_by(
            versions.c.title, versions.c.version_id).limit(10)).all()
        groups = [_sections(base_id, str(entry.version_id), limit=2) for entry in entries]
        candidates = [g[i] for i in range(2) for g in groups if len(g) > i]
        scope.update(total_documents=total, coverage="sampled_sections")
        return {"overview": True, "candidates": candidates, "scope": scope, "anchors": []}
    lexical = _lexical(base_id, terms)
    db.session.rollback()
    fallback = False
    try:
        vector, _ = state["search"](base_id, question, top_k=24)
    except EmbeddingError:
        if not lexical and not anchors:
            raise
        vector, fallback = [], True
    ranked = _merge_ranked(vector, lexical)
    scope["retrieval"] = {"embedding_fallback": fallback,
        "vector": [{"chunk_id": s["chunk_id"], "score": s.get("score")} for s in vector],
        "lexical": [s["chunk_id"] for s in lexical]}
    return {"overview": False, "candidates": ranked, "anchors": anchors, "scope": scope}


def _rank(state):
    if state["overview"]:
        return {}
    return {"candidates": rerank_sources(state["question"], state["candidates"],
                enabled=current_app.config.get("QA_RERANK_ENABLED", False))}


def _expand(state):
    ranked, anchors, scope = state["candidates"], state["anchors"], dict(state["scope"])
    base_id, mode = state["base_id"], scope["mode"]
    media = []
    if state["overview"]:
        candidates = ranked
    else:
        text_ranked = [s for s in ranked if s["modality"] == "text"]
        seeds = list({s["chunk_id"]: s for s in anchors + text_ranked}.values())[:4]
        neighbours = _neighbours(base_id, seeds)
        if mode in {"overview", "workflow"}:
            versions = list(dict.fromkeys(s["version_id"] for s in anchors + text_ranked))[:2]
            groups = [_sections(base_id, vid, limit=6) for vid in versions]
            sections = [g[i] for i in range(6) for g in groups if len(g) > i]
            candidates = anchors + text_ranked[:2] + sections + neighbours + text_ranked[2:]
            scope["coverage"] = "sampled_sections"
        else:
            candidates = anchors + text_ranked[:4] + neighbours + text_ranked[4:]
        media = [s for s in ranked if s["modality"] in {"image", "video"}][:3]
    context = _context(candidates)
    scope["covered_documents"] = len({s["document_id"] for s in context})
    scope["catalog"] = list(dict.fromkeys(s["document_title"] for s in context))
    scope.setdefault("retrieval", {})["ranked"] = [
        {"chunk_id": s["chunk_id"], "score": s.get("score"), "rerank_score": s.get("rerank_score"), "document_title": s["document_title"],
         "document_id": s["document_id"], "index_config_hash": s.get("index_config_hash"),
         "rerank_fallback": s.get("rerank_fallback", False)}
        for s in ranked]
    scope["retrieval"]["selected"] = [s["chunk_id"] for s in context]
    scope["retrieval"]["context_documents"] = [s["document_title"] for s in context]
    scope["retrieval"]["context_document_ids"] = [s["document_id"] for s in context]
    scope["retrieval"]["reranker"] = current_app.config.get("QA_RERANK_PROVIDER", "lexical") if current_app.config.get("QA_RERANK_ENABLED") else "disabled"
    return {"result": AnswerMaterial(context, media, scope,
                len({s["chunk_id"] for s in candidates + media}))}


def _retrieval_graph():
    from typing import Any, TypedDict

    from langgraph.graph import END, START, StateGraph
    class State(TypedDict, total=False):
        base_id: Any
        question: str
        anchor_id: str | None
        search: Any
        candidates: list
        anchors: list
        overview: bool
        scope: dict
        result: Any
    graph = StateGraph(State)
    graph.add_node("hybrid_recall", _recall)
    graph.add_node("rerank", _rank)
    graph.add_node("expand_context", _expand)
    graph.add_edge(START, "hybrid_recall")
    graph.add_edge("hybrid_recall", "rerank")
    graph.add_edge("rerank", "expand_context")
    graph.add_edge("expand_context", END)
    return graph.compile(name="hybrid_retrieval")


retrieval_graph = _retrieval_graph()


def retrieve_for_answer(base_id, question, *, anchor_id=None, search_sources_fn=default_search_sources):
    from ...integrations.ai.langsmith_config import tracing_scope
    with tracing_scope():
        return retrieval_graph.invoke({"base_id": base_id, "question": question,
            "anchor_id": anchor_id, "search": search_sources_fn},
            config={"run_name": "rag.retrieval", "recursion_limit": 8})["result"]
