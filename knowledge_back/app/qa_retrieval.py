"""Question-aware retrieval: semantic/lexical search, section coverage and neighbours."""

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from flask import current_app
from sqlalchemy import case, func, or_
from sqlalchemy.orm import defer

from .embedding import EmbeddingError
from .extensions import db
from .http import ApiError
from .models import Document, DocumentChunk, DocumentVersion
from .retrieval import available_chunks, search_sources, source_from_row

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
        )
        .where(DocumentChunk.id.in_([UUID(s["chunk_id"]) for s in seeds]))
    ).all()
    conditions = [
        (DocumentChunk.document_version_id == version_id)
        & DocumentChunk.chunk_index.between(index - 1, index + 1)
        for version_id, index in selected
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
    chosen, ids, texts, budget = [], set(), set(), 24000
    for source in candidates:
        if source["modality"] != "text" or not source["content"] or source["chunk_id"] in ids:
            continue
        content = source["content"].strip()
        key = re.sub(r"\s+", "", content)
        if not key or key in texts or len(content) > budget:
            continue
        # Indexed chunks already have a bound. Do not truncate a command/code block
        # again at an arbitrary 3,000-character boundary.
        ids.add(source["chunk_id"])
        texts.add(key)
        budget -= len(content)
        chosen.append({**source, "source_id": str(len(chosen) + 1), "content": content})
        if len(chosen) == 10:
            break
    return chosen


def retrieve_for_answer(base_id, question, *, anchor_id=None):
    mode, terms = question_mode(question), _terms(question)
    anchors = _anchor(base_id, anchor_id)
    # Generic questions refer to the selected knowledge base in this single-turn UI.
    global_overview = mode == "overview" and not terms and not anchors
    scope = {"mode": mode, "coverage": "retrieved_sections"}
    if global_overview:
        versions = (
            _text_query(base_id)
            .with_only_columns(
                DocumentVersion.id.label("version_id"),
                Document.title.label("title"),
            )
            .distinct()
            .subquery()
        )
        total = db.session.scalar(db.select(func.count()).select_from(versions))
        entries = db.session.execute(
            db.select(versions).order_by(versions.c.title, versions.c.version_id).limit(10)
        ).all()
        groups = [_sections(base_id, str(entry.version_id), limit=2) for entry in entries]
        candidates = [group[index] for index in range(2) for group in groups if len(group) > index]
        context = _context(candidates)
        scope.update(
            total_documents=total,
            covered_documents=len({s["document_id"] for s in context}),
            coverage="sampled_sections",
            catalog=list(dict.fromkeys(source["document_title"] for source in context)),
        )
        return AnswerMaterial(context, [], scope, len(candidates))

    lexical = _lexical(base_id, terms)
    db.session.rollback()  # Release the database connection while embedding the question.
    try:
        vector, _ = search_sources(base_id, question, top_k=24)
    except EmbeddingError:
        if not lexical and not anchors:
            raise
        logger.info("qa_retrieval_fallback method=lexical_or_recommendation")
        vector = []
    ranked = _merge_ranked(vector, lexical)
    text_ranked = [source for source in ranked if source["modality"] == "text"]
    seeds = list({source["chunk_id"]: source for source in anchors + text_ranked}.values())[:4]
    neighbours = _neighbours(base_id, seeds)
    if mode in {"overview", "workflow"}:
        versions = list(dict.fromkeys(source["version_id"] for source in anchors + text_ranked))[:2]
        groups = [_sections(base_id, version_id, limit=6) for version_id in versions]
        sections = [group[index] for index in range(6) for group in groups if len(group) > index]
        candidates = anchors + text_ranked[:2] + sections + neighbours + text_ranked[2:]
        scope["coverage"] = "sampled_sections"
    else:
        candidates = anchors + text_ranked[:4] + neighbours + text_ranked[4:]
    context = _context(candidates)
    media = [source for source in ranked if source["modality"] in {"image", "video"}][:3]
    scope["covered_documents"] = len({s["document_id"] for s in context})
    return AnswerMaterial(context, media, scope, len({s["chunk_id"] for s in candidates + media}))
