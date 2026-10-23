"""Grounded recommendations and single-turn answers over current indexed documents."""

import re
from datetime import timedelta
from time import monotonic
from uuid import UUID, uuid4

from flask import Blueprint, current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .auth import authenticated
from .chat import ChatError
from .embedding import EmbeddingError
from .extensions import db, limiter
from .grounding import NO_EVIDENCE, generate_answer, generate_suggestions
from .http import ApiError, success
from .models import DocumentChunk, QALog, now
from .qa_retrieval import retrieve_for_answer
from .retrieval import (
    available_chunks,
    require_knowledge_base,
    validate_question,
    with_preview_urls,
)

qa = Blueprint("qa", __name__, url_prefix="/api/v1")


def _body(allowed):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - allowed:
        raise ApiError("请求参数不正确", 422)
    return body


def _normalized(value):
    return re.sub(r"\s+", "", value)


def _verify_current(knowledge_base_id, sources):
    require_knowledge_base(knowledge_base_id)
    if not sources:
        return
    ids = {UUID(source["chunk_id"]) for source in sources}
    query = available_chunks(
        knowledge_base_id, current_app.config["DASHSCOPE_EMBEDDING_MODEL"].strip()
    )
    found = {chunk.id for chunk, _, _ in db.session.execute(query.where(DocumentChunk.id.in_(ids)))}
    if found != ids:
        raise ApiError("知识库文档已更新，请重新提问或刷新推荐问题", 409, 40903)


def _sample_material(knowledge_base_id):
    model = current_app.config["DASHSCOPE_EMBEDDING_MODEL"].strip()
    # Sample documents first so one large document cannot dominate all recommendations.
    query = available_chunks(knowledge_base_id, model).where(
        func.coalesce(DocumentChunk.chunk_metadata["modality"].as_string(), "text") == "text",
        func.length(func.trim(DocumentChunk.content)) >= 40,
    )
    candidates = query.with_only_columns(
        DocumentChunk.id, DocumentChunk.document_version_id
    ).subquery()
    versions = db.session.scalars(
        db.select(candidates.c.document_version_id)
        .group_by(candidates.c.document_version_id)
        .order_by(func.random())
        .limit(3)
    ).all()
    result, seen = [], set()
    for version_id in versions:
        rows = db.session.execute(
            query.where(DocumentChunk.document_version_id == version_id)
            .order_by(func.random())
            .limit(12)
        ).all()
        sections, chosen = set(), 0
        # Prefer distinct sections; use other chunks if headings are absent or repeated.
        ordered = []
        for row in rows:
            heading = row[0].heading_path
            if heading and heading not in sections:
                ordered.append(row)
                sections.add(heading)
        ordered.extend(row for row in rows if row not in ordered)
        for chunk, version, document in ordered:
            content = chunk.content.strip()
            normalized = _normalized(content)
            if normalized in seen or len(re.findall(r"\w", content)) < 30:
                continue
            seen.add(normalized)
            result.append(
                {
                    "source_id": str(len(result) + 1),
                    "chunk_id": str(chunk.id),
                    "document_id": str(document.id),
                    "document_title": document.title,
                    "version_id": str(version.id),
                    "version_no": version.version_no,
                    "heading_path": chunk.heading_path,
                    "content": content,
                }
            )
            chosen += 1
            if chosen == 3:
                break
    return result


def _suggestion_signer():
    return URLSafeTimedSerializer(current_app.config["JWT_SECRET_KEY"], salt="qa-suggestion-v1")


def _suggestion_anchor(token, user_id, base_id, question):
    if token is None:
        return None
    if not isinstance(token, str) or not 1 <= len(token) <= 4096:
        raise ApiError("推荐问题凭据格式不正确", 422)
    try:
        data = _suggestion_signer().loads(token, max_age=8 * 3600)
        if not isinstance(data, dict) or (
            data.get("user_id") != str(user_id)
            or data.get("base_id") != str(base_id)
            or data.get("question") != question
        ):
            raise ValueError
        return str(UUID(data["chunk_id"]))
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        raise ApiError("推荐问题已失效，请刷新推荐或重新输入问题", 409, 40903) from None


@qa.post("/web/suggested-questions")
@authenticated
@limiter.limit("12 per minute", key_func=lambda: str(g.user.id))
def suggested_questions():
    body = _body({"knowledge_base_id"})
    base_id = require_knowledge_base(body.get("knowledge_base_id")).id
    user_id = g.user.id
    material = _sample_material(base_id)
    db.session.rollback()
    if not material:
        return success({"knowledge_base_id": str(base_id), "questions": [], "status": "empty"})
    try:
        questions = generate_suggestions(material)
        _verify_current(base_id, [item["source"] for item in questions])
        for item in questions:
            item["suggestion_token"] = _suggestion_signer().dumps(
                {
                    "base_id": str(base_id),
                    "user_id": str(user_id),
                    "question": item["question"],
                    "chunk_id": item["source"]["chunk_id"],
                }
            )
        return success(
            {
                "knowledge_base_id": str(base_id),
                "questions": questions,
                "status": "ready" if questions else "empty",
            }
        )
    except ChatError as error:
        raise ApiError(str(error), 503, 50002) from None


def _claim_request(request_id, user_id, base_id, question):
    log = db.session.scalar(db.select(QALog).where(QALog.request_id == request_id))
    if log is None:
        log = QALog(
            id=uuid4(),
            request_id=request_id,
            source_type="WEB",
            user_id=user_id,
            knowledge_base_id=base_id,
            question=question,
            status="PROCESSING",
            sources=[],
            retrieval_count=0,
        )
        db.session.add(log)
        try:
            db.session.commit()
            return log, True
        except IntegrityError:
            db.session.rollback()
            log = db.session.scalar(db.select(QALog).where(QALog.request_id == request_id))
            if log is None:
                raise
    if (
        log.user_id != user_id
        or log.source_type != "WEB"
        or log.knowledge_base_id != base_id
        or log.question != question
    ):
        raise ApiError("请求编号已被使用，请重新提问", 409, 40901)
    if log.status in {"SUCCESS", "PARTIAL", "NO_EVIDENCE", "SOURCES_ONLY"}:
        return log, False
    # A crashed request can be reclaimed after ten minutes. Compare-and-swap also
    # prevents two concurrent retries from taking the same failed request.
    updated = db.session.execute(
        db.update(QALog)
        .where(
            QALog.id == log.id,
            QALog.updated_at == log.updated_at,
            (QALog.status == "FAILED")
            | ((QALog.status == "PROCESSING") & (QALog.updated_at < now() - timedelta(minutes=10))),
        )
        .values(status="PROCESSING", error_message=None, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        db.session.rollback()
        raise ApiError("该问题正在处理中，请稍后点击重试获取结果", 409, 40902)
    log_id = log.id
    db.session.commit()
    return db.session.get(QALog, log_id, populate_existing=True), True


def _finish_request(log_id, lease, **values):
    result = db.session.execute(
        db.update(QALog)
        .where(
            QALog.id == log_id,
            QALog.status == "PROCESSING",
            QALog.updated_at == lease,
        )
        .values(**values, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    if result.rowcount != 1:
        raise ApiError("本次请求已由其他重试接管，请重试获取结果", 409, 40902)


def _log_response(log):
    sources = log.sources or []
    _verify_current(log.knowledge_base_id, sources)
    return success(
        {
            "request_id": log.request_id,
            "knowledge_base_id": str(log.knowledge_base_id),
            "question": log.question,
            "answer": log.answer,
            "answer_status": {
                "SUCCESS": "answered",
                "PARTIAL": "partial",
                "SOURCES_ONLY": "sources_only",
            }.get(log.status, "insufficient_evidence"),
            "sources": with_preview_urls(sources),
            "model": log.model_name,
            "latency_ms": log.latency_ms,
        }
    )


@qa.post("/web/query")
@authenticated
@limiter.limit("20 per minute", key_func=lambda: str(g.user.id))
def query():
    body = _body({"knowledge_base_id", "question", "request_id", "suggestion_token"})
    question = validate_question(body.get("question"))
    request_id = body.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", request_id):
        raise ApiError("请提供 1–100 位字母、数字或 ._- 组成的请求编号", 422)
    base_id = require_knowledge_base(body.get("knowledge_base_id")).id
    anchor_id = _suggestion_anchor(body.get("suggestion_token"), g.user.id, base_id, question)
    log, claimed = _claim_request(request_id, g.user.id, base_id, question)
    if not claimed:
        return _log_response(log)
    log_id, lease = log.id, log.updated_at
    db.session.rollback()
    started = monotonic()
    try:
        material = retrieve_for_answer(base_id, question, anchor_id=anchor_id)
        context, media = material.context, material.media
        db.session.rollback()
        answer, citations, model, status = NO_EVIDENCE, [], None, "NO_EVIDENCE"
        if context:
            answer, citations, model, status = generate_answer(
                question, context, scope=material.scope
            )
        if not context and media:
            answer = "找到了相关图片或视频，但目前没有足够的文字资料生成可靠回答，请查看相关来源。"
        if (
            status in {"SUCCESS", "PARTIAL"}
            and material.scope.get("coverage") == "sampled_sections"
        ):
            covered = material.scope["covered_documents"]
            total = material.scope.get("total_documents")
            if total is not None:
                answer += (
                    f"\n\n本次概览参考了 {covered}/{total} 篇已索引文字资料的代表章节，未阅读全文。"
                )
            else:
                answer += f"\n\n以上整理基于 {covered} 篇相关文档中检索到的章节。"
        _verify_current(base_id, citations + media)
    except Exception as error:
        db.session.rollback()
        message = (
            str(error)
            if isinstance(error, (ChatError, EmbeddingError))
            else (error.message if isinstance(error, ApiError) else "问答暂时不可用，请稍后重试")
        )
        _finish_request(
            log_id,
            lease,
            status="FAILED",
            error_message=message,
            latency_ms=int((monotonic() - started) * 1000),
        )
        if isinstance(error, ApiError):
            raise
        # Do not log provider payloads, document contents or credentials.
        current_app.logger.warning(
            "qa failed request_id=%s type=%s", request_id, type(error).__name__
        )
        raise ApiError(message, 503, 50002) from None
    _finish_request(
        log_id,
        lease,
        status=status,
        answer=answer,
        sources=citations + media,
        retrieval_count=material.retrieval_count,
        model_name=model,
        error_message=None,
        latency_ms=int((monotonic() - started) * 1000),
    )
    return _log_response(db.session.get(QALog, log_id, populate_existing=True))
