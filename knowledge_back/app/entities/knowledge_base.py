"""Knowledge-base persistence entity."""

from ..core.extensions import db
from .base import Record


class KnowledgeBase(Record, db.Model):
    __tablename__ = "knowledge_bases"
    code = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="active")
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))


__all__ = ["KnowledgeBase"]
