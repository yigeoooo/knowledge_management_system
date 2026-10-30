"""Document, version, chunk, and indexing entities."""

from pgvector.sqlalchemy import Vector

from ..core.extensions import db
from .base import Record


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
    # Dimension is validated after the first real embedding response.
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


__all__ = ["Document", "DocumentChunk", "DocumentVersion", "IndexTask"]
