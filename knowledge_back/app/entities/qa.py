"""Question-and-answer history entity."""

from ..core.extensions import db
from .base import Record
from .identity import User
from .robot import Robot


class QALog(Record, db.Model):
    __tablename__ = "qa_logs"
    request_id = db.Column(db.String(100), nullable=False, unique=True)
    source_type = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Uuid, db.ForeignKey("users.id"))
    robot_id = db.Column(db.Uuid, db.ForeignKey("robots.id"))
    user = db.relationship(User)
    robot = db.relationship(Robot)
    knowledge_base_id = db.Column(db.Uuid, db.ForeignKey("knowledge_bases.id"), nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text)
    sources = db.Column(db.JSON)
    retrieval_count = db.Column(db.Integer)
    model_name = db.Column(db.String(200))
    status = db.Column(db.String(30), nullable=False)
    error_message = db.Column(db.Text)
    latency_ms = db.Column(db.Integer)
    conversation_id = db.Column(db.Uuid, db.ForeignKey("qa_conversations.id"))
    turn_no = db.Column(db.Integer)
    resolved_question = db.Column(db.Text)
    answer_kind = db.Column(db.String(30), nullable=False, default="knowledge", server_default="knowledge")
    context_snapshot = db.Column(db.JSON)
    prompt_snapshot = db.Column(db.JSON)
    execution_trace = db.Column(db.JSON)
    lease_token = db.Column(db.Uuid)
    lease_expires_at = db.Column(db.DateTime(timezone=True))
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    suggestion_anchor = db.Column(db.String(36))
    __table_args__ = (
        db.UniqueConstraint("conversation_id", "turn_no", name="uq_conversation_turn"),
        db.Index("ix_qa_pending", "status", "lease_expires_at", "created_at"),
        db.Index(
            "uq_conversation_inflight", "conversation_id", unique=True,
            postgresql_where=db.text("status IN ('PENDING', 'PROCESSING') AND conversation_id IS NOT NULL"),
            sqlite_where=db.text("status IN ('PENDING', 'PROCESSING') AND conversation_id IS NOT NULL"),
        ),
    )


__all__ = ["QALog"]
