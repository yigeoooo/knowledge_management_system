"""Backward-compatible entity imports.

The mapped classes now live in :mod:`app.entities`, grouped by persistence
domain.  Existing extensions and tests may keep importing ``app.models``
while the migration is completed.
"""

from .entities import (
    AuditLog,
    Document,
    DocumentChunk,
    DocumentVersion,
    IndexTask,
    KnowledgeBase,
    Page,
    QALog,
    Record,
    Robot,
    Role,
    RolePagePermission,
    User,
    UserSession,
    now,
)

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
