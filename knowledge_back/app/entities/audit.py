"""Audit trail entity."""

from ..core.extensions import db
from .base import Record
from .identity import User


class AuditLog(Record, db.Model):
    __tablename__ = "audit_logs"
    user_id = db.Column(db.Uuid, db.ForeignKey("users.id"))
    operator = db.relationship(User)
    action = db.Column(db.String(100), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.Uuid)
    detail = db.Column(db.JSON, nullable=False, default=dict)
    ip_address = db.Column(db.String(64))


__all__ = ["AuditLog"]
