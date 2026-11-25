"""Shared SQLAlchemy fields for all persisted entities."""

from datetime import UTC, datetime
from uuid import uuid4

from ..core.extensions import db


def now():
    """Return the UTC timestamp used by database defaults and services."""

    return datetime.now(UTC)


class Record:
    """Common identity and audit timestamps for application entities."""

    id = db.Column(db.Uuid, primary_key=True, default=uuid4)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now, onupdate=now)


__all__ = ["Record", "now"]
