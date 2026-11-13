"""Robot client entity."""

from ..core.extensions import db
from .base import Record


class Robot(Record, db.Model):
    __tablename__ = "robots"
    serial_no = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200))
    description = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="active")
    last_request_at = db.Column(db.DateTime(timezone=True))
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    knowledge_base_id = db.Column(db.Uuid, db.ForeignKey("knowledge_bases.id"))
    default_location_name = db.Column(db.String(300))
    default_location = db.Column(db.String(200))
    timezone = db.Column(db.String(100))
    binding_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")


__all__ = ["Robot"]
