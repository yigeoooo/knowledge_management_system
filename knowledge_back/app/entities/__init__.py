"""Canonical database entity package.

Importing this package registers every mapped class on the shared SQLAlchemy
metadata.  Keeping the import list explicit makes Alembic and tests reliable
after entities are split across focused modules.
"""

from ..core.extensions import db

# Keep schema descriptions attached after all tables have been registered.
from ..schema_comments import describe_schema
from .audit import AuditLog
from .base import Record, now
from .document import Document, DocumentChunk, DocumentVersion, IndexTask
from .identity import Page, Role, RolePagePermission, User, UserSession
from .knowledge_base import KnowledgeBase
from .qa import QALog
from .robot import Robot

describe_schema(db.metadata)

__all__ = [
    "AuditLog",
    "Document",
    "DocumentChunk",
    "DocumentVersion",
    "IndexTask",
    "KnowledgeBase",
    "Page",
    "QALog",
    "Record",
    "Robot",
    "Role",
    "RolePagePermission",
    "User",
    "UserSession",
    "now",
]
