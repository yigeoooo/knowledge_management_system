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


__all__ = ["QALog"]
