from datetime import UTC, datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector

from .extensions import db
from .schema_comments import describe_schema


def now():
    return datetime.now(UTC)


class Record:
    id = db.Column(db.Uuid, primary_key=True, default=uuid4)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now, onupdate=now)


class Role(Record, db.Model):
    __tablename__ = "roles"
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    description = db.Column(db.Text)


class User(Record, db.Model):
    __tablename__ = "users"
    username = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    password_plaintext = db.Column(db.String(1024))
    role_id = db.Column(db.Uuid, db.ForeignKey("roles.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    role = db.relationship(Role)


class Page(Record, db.Model):
    __tablename__ = "pages"
    code = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    route_path = db.Column(db.String(255), unique=True, nullable=False)
    route_name = db.Column(db.String(100), nullable=False)
    component_key = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(db.Uuid, db.ForeignKey("pages.id"))
    page_type = db.Column(db.String(30), nullable=False, default="menu")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_visible = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(30), nullable=False, default="active")


class RolePagePermission(db.Model):
    __tablename__ = "role_page_permissions"
    role_id = db.Column(db.Uuid, db.ForeignKey("roles.id"), primary_key=True)
    page_id = db.Column(db.Uuid, db.ForeignKey("pages.id"), primary_key=True)
    can_view = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class UserSession(Record, db.Model):
    __tablename__ = "user_sessions"
    user_id = db.Column(db.Uuid, db.ForeignKey("users.id"), nullable=False, index=True)
    refresh_token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))
    user_agent = db.Column(db.Text)
    ip_address = db.Column(db.String(64))


class KnowledgeBase(Record, db.Model):
    __tablename__ = "knowledge_bases"
    code = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="active")
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))


class AuditLog(Record, db.Model):
    __tablename__ = "audit_logs"
    user_id = db.Column(db.Uuid, db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.Uuid)
    detail = db.Column(db.JSON, nullable=False, default=dict)
    ip_address = db.Column(db.String(64))


class Robot(Record, db.Model):
    __tablename__ = "robots"
    serial_no = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200))
    description = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="active")
    last_request_at = db.Column(db.DateTime(timezone=True))
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))


class Document(Record, db.Model):
    __tablename__ = "documents"
    knowledge_base_id = db.Column(db.Uuid, db.ForeignKey("knowledge_bases.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    current_version_id = db.Column(
        db.Uuid,
        db.ForeignKey("document_versions.id", use_alter=True, name="fk_documents_current_version"),
    )
    status = db.Column(db.String(30), nullable=False, default="active")
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    __table_args__ = (db.Index("idx_documents_kb_status", "knowledge_base_id", "status"),)


class DocumentVersion(Record, db.Model):
    __tablename__ = "document_versions"
    document_id = db.Column(db.Uuid, db.ForeignKey("documents.id"), nullable=False)
    version_no = db.Column(db.Integer, nullable=False)
    minio_bucket = db.Column(db.String(100), nullable=False)
    minio_object_key = db.Column(db.String(500), nullable=False, unique=True)
    filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100))
    file_size = db.Column(db.BigInteger, nullable=False)
    content_hash = db.Column(db.String(64))
    status = db.Column(db.String(30), nullable=False, default="UPLOADED")
    chunk_count = db.Column(db.Integer, nullable=False, default=0)
    embedding_model = db.Column(db.String(200))
    error_message = db.Column(db.Text)
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    __table_args__ = (db.UniqueConstraint("document_id", "version_no"),)


class DocumentChunk(Record, db.Model):
    __tablename__ = "document_chunks"
    document_version_id = db.Column(db.Uuid, db.ForeignKey("document_versions.id"), nullable=False)
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    heading_path = db.Column(db.Text)
    token_count = db.Column(db.Integer)
    # Dimension stays unconstrained until the first real DashScope response is validated.
    embedding = db.Column(Vector().with_variant(db.JSON(), "sqlite"), nullable=False)
    chunk_metadata = db.Column("metadata", db.JSON, nullable=False, default=dict)
    __table_args__ = (db.UniqueConstraint("document_version_id", "chunk_index"),)


class IndexTask(Record, db.Model):
    __tablename__ = "index_tasks"
    document_version_id = db.Column(db.Uuid, db.ForeignKey("document_versions.id"), nullable=False)
    task_type = db.Column(db.String(30), nullable=False, default="INDEX")
    status = db.Column(db.String(30), nullable=False, default="PENDING")
    attempts = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))


class QALog(Record, db.Model):
    __tablename__ = "qa_logs"
    request_id = db.Column(db.String(100), nullable=False, unique=True)
    source_type = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Uuid, db.ForeignKey("users.id"))
    robot_id = db.Column(db.Uuid, db.ForeignKey("robots.id"))
    knowledge_base_id = db.Column(db.Uuid, db.ForeignKey("knowledge_bases.id"), nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text)
    sources = db.Column(db.JSON)
    retrieval_count = db.Column(db.Integer)
    model_name = db.Column(db.String(200))
    status = db.Column(db.String(30), nullable=False)
    error_message = db.Column(db.Text)
    latency_ms = db.Column(db.Integer)


describe_schema(db.metadata)
