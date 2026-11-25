"""Grounded recommendations and single-turn answers over current indexed documents."""

import re
from datetime import timedelta
from time import monotonic
from uuid import UUID, uuid4

from flask import Blueprint, current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ...api.auth.controller import page_required
from ...api.retrieval.controller import (
    require_knowledge_base,
    validate_question,
    with_preview_urls,
)
from ...application.qa.grounding_service import generate_suggestions
from ...application.qa.search_service import available_chunks
from ...core.extensions import db, limiter
from ...core.http import ApiError, success
from ...entities import DocumentChunk, QAConversation, QALog, now
from ...integrations.ai.chat_adapter import ChatError
from ...integrations.ai.embedding_adapter import EmbeddingError
from ...processors.answer_text import answer_text
from ...processors.pdf import readable_answer

qa = Blueprint("qa", __name__, url_prefix="/api/v1")


def _body(allowed):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - allowed:
        raise ApiError("请求参数不正确", 422)
    return body


def _request_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value):
        raise ApiError("请提供 1–100 位字母、数字或 ._- 组成的请求编号", 422)
    return value


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
@page_required("/qa")
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


def _claim_request(request_id, user_id, base_id, question, *, robot_id=None):
    source_type = "ROBOT" if robot_id is not None else "WEB"
    log = db.session.scalar(db.select(QALog).where(QALog.request_id == request_id))
    if log is None:
        conversation = QAConversation(
            id=uuid4(), source_type=source_type, user_id=user_id, robot_id=robot_id,
            knowledge_base_id=base_id, title=question[:80], creation_request_id=request_id,
            next_turn_no=2,
        )
        db.session.add(conversation)
        log = QALog(
            conversation_id=conversation.id, turn_no=1,
            id=uuid4(),
            request_id=request_id,
            source_type=source_type,
            user_id=user_id,
            robot_id=robot_id,
            knowledge_base_id=base_id,
            question=question,
            status="PROCESSING",
            sources=[],
            retrieval_count=0,
        )
        try:
            db.session.flush()  # Persist the parent before the turn, inside the same transaction.
            db.session.add(log)
            db.session.commit()
            return log, True
        except IntegrityError:
            db.session.rollback()
            log = db.session.scalar(db.select(QALog).where(QALog.request_id == request_id))
            if log is None:
                raise
    if (
        log.user_id != user_id
        or log.robot_id != robot_id
        or log.source_type != source_type
        or log.knowledge_base_id != base_id
        or log.question != question
    ):
        raise ApiError("请求编号已被使用，请重新提问", 409, 40901)
    if log.conversation_id:
        from ...application.conversations.service import get_conversation, writable
        writable(get_conversation(log.conversation_id, user_id=user_id, robot_id=robot_id))
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
    from ...application.conversations.service import get_conversation, writable
    log = db.session.get(QALog, log_id)
    if log and log.conversation_id:
        writable(get_conversation(log.conversation_id, user_id=log.user_id, robot_id=log.robot_id, lock=True))
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
    if log.source_type == "ROBOT":
        if log.status in {"NO_EVIDENCE", "SOURCES_ONLY"}:
            answer = "当前知识库资料不足以给出可靠回答，请补充具体问题或相关资料。"
        else:
            answer = answer_text(readable_answer(log.answer, sources), sources)
        return success({"answer": answer})
    return success(
        {
            "request_id": log.request_id,
            "knowledge_base_id": str(log.knowledge_base_id),
            "question": log.question,
            "answer": readable_answer(log.answer, sources),
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
@page_required("/qa")
@limiter.limit("20 per minute", key_func=lambda: str(g.user.id))
def query():
    body = _body({"knowledge_base_id", "question", "request_id", "suggestion_token"})
    question = validate_question(body.get("question"))
    request_id = _request_id(body.get("request_id"))
    base_id = require_knowledge_base(body.get("knowledge_base_id")).id
    anchor_id = _suggestion_anchor(body.get("suggestion_token"), g.user.id, base_id, question)
    return _answer_question(request_id, base_id, question, user_id=g.user.id, anchor_id=anchor_id)



def _answer_question(request_id, base_id, question, *, user_id=None, robot_id=None, anchor_id=None):
    """Use the same retrieval, grounding and retry handling for both callers."""
    log, claimed = _claim_request(request_id, user_id, base_id, question, robot_id=robot_id)
    if not claimed:
        return _log_response(log)
    log_id, lease = log.id, log.updated_at
    db.session.rollback()
    started = monotonic()
    try:
        from ...application.qa.workflow import answer_question
        result = answer_question(question, base_id, {}, anchor_id, robot=robot_id is not None,
                                 trace_context={"turn_id": log_id, "knowledge_base_id": base_id})
        _verify_current(base_id, result["sources"])
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
        current_app.logger.exception(
            "qa failed request_id=%s type=%s", request_id, type(error).__name__
        )
        raise ApiError(message, 503, 50002) from None
    _finish_request(
        log_id,
        lease,
        **result,
        error_message=None,
        latency_ms=int((monotonic() - started) * 1000),
    )
    return _log_response(db.session.get(QALog, log_id, populate_existing=True))
