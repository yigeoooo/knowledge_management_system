"""Versioned prompt releases, curated test sets and reproducible experiments."""

from ..core.extensions import db
from .base import Record, now


class PromptTemplate(db.Model):
    __tablename__ = "prompt_templates"
    key = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    active_version = db.Column(db.Integer, nullable=False)
    generation = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now, onupdate=now)


class PromptVersion(Record, db.Model):
    __tablename__ = "prompt_versions"
    prompt_key = db.Column(db.String(64), db.ForeignKey("prompt_templates.key"), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    note = db.Column(db.String(1000), nullable=False, default="")
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    __table_args__ = (db.UniqueConstraint("prompt_key", "version", name="uq_prompt_version"),)


class EvaluationDataset(Record, db.Model):
    __tablename__ = "evaluation_datasets"
    name = db.Column(db.String(200), nullable=False)
    knowledge_base_id = db.Column(db.Uuid, db.ForeignKey("knowledge_bases.id"), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    __table_args__ = (
        db.UniqueConstraint("knowledge_base_id", name="uq_evaluation_dataset_knowledge_base"),
    )


class EvaluationExample(Record, db.Model):
    __tablename__ = "evaluation_examples"
    dataset_id = db.Column(
        db.Uuid, db.ForeignKey("evaluation_datasets.id"), nullable=False, index=True
    )
    name = db.Column(db.String(200), nullable=False)
    inputs = db.Column(db.JSON, nullable=False)
    reference = db.Column(db.JSON, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    reviewed_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    __table_args__ = (db.UniqueConstraint("dataset_id", "name", name="uq_evaluation_example"),)


class EvaluationRun(Record, db.Model):
    __tablename__ = "evaluation_runs"
    dataset_id = db.Column(db.Uuid, db.ForeignKey("evaluation_datasets.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="PENDING")
    snapshot = db.Column(db.JSON, nullable=False)
    results = db.Column(db.JSON, nullable=False, default=list)
    error_message = db.Column(db.String(500))
    lease_token = db.Column(db.Uuid)
    lease_expires_at = db.Column(db.DateTime(timezone=True))
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Uuid, db.ForeignKey("users.id"))
    __table_args__ = (db.Index("ix_evaluation_pending", "status", "lease_expires_at"),)
