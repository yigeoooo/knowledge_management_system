"""Owned conversations; memories never cross this persistence boundary."""

from ..core.extensions import db
from .base import Record, now


class QAConversation(Record, db.Model):
    __tablename__ = "qa_conversations"
    source_type = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Uuid, db.ForeignKey("users.id"))
    robot_id = db.Column(db.Uuid, db.ForeignKey("robots.id"))
    knowledge_base_id = db.Column(db.Uuid, db.ForeignKey("knowledge_bases.id"), nullable=False)
    robot_binding_version = db.Column(db.Integer)
    title = db.Column(db.String(100), nullable=False)
    creation_request_id = db.Column(db.String(100), nullable=False)
    next_turn_no = db.Column(db.Integer, nullable=False, default=1)
    last_message_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    deleted_at = db.Column(db.DateTime(timezone=True))
    closed_at = db.Column(db.DateTime(timezone=True))
    closed_reason = db.Column(db.String(100))
    memory_summary = db.Column(db.Text, nullable=False, default="")
    summary_through_turn_no = db.Column(db.Integer, nullable=False, default=0)
    memory_version = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (
        db.CheckConstraint(
            "(source_type = 'WEB' AND user_id IS NOT NULL AND robot_id IS NULL) OR "
            "(source_type = 'ROBOT' AND robot_id IS NOT NULL AND user_id IS NULL)",
            name="ck_conversation_owner",
        ),
        db.UniqueConstraint("user_id", "creation_request_id", name="uq_conversation_user_request"),
        db.UniqueConstraint(
            "robot_id", "creation_request_id", name="uq_conversation_robot_request"
        ),
        db.Index("ix_conversation_user_history", "user_id", "deleted_at", "last_message_at", "id"),
        db.Index("ix_conversation_robot_history", "robot_id", "last_message_at", "id"),
    )
