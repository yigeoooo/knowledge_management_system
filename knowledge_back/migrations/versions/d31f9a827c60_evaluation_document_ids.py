"""Bind existing evaluation document labels to unambiguous document IDs.

Revision ID: d31f9a827c60
Revises: c92ea640d815
"""

from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "d31f9a827c60"
down_revision = "c92ea640d815"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    examples = sa.table(
        "evaluation_examples",
        sa.column("id", sa.Uuid),
        sa.column("dataset_id", sa.Uuid),
        sa.column("reference", sa.JSON),
        sa.column("revision", sa.Integer),
        sa.column("reviewed_by", sa.Uuid),
        sa.column("reviewed_at", sa.DateTime),
    )
    datasets = sa.table(
        "evaluation_datasets", sa.column("id", sa.Uuid), sa.column("knowledge_base_id", sa.Uuid)
    )
    documents = sa.table(
        "documents",
        sa.column("id", sa.Uuid),
        sa.column("knowledge_base_id", sa.Uuid),
        sa.column("title", sa.String),
        sa.column("status", sa.String),
    )
    titles = defaultdict(list)
    for row in connection.execute(
        sa.select(documents).where(documents.c.status == "active")
    ).mappings():
        titles[(row["knowledge_base_id"], row["title"])].append(str(row["id"]))
    rows = (
        connection.execute(
            sa.select(examples, datasets.c.knowledge_base_id).join(
                datasets, examples.c.dataset_id == datasets.c.id
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        reference = dict(row["reference"])
        if "expected_document_ids" in reference:
            continue
        labels = reference.get("expected_documents") or []
        matches = [titles[(row["knowledge_base_id"], label)] for label in labels]
        values = {"revision": row["revision"] + 1}
        if all(len(ids) == 1 for ids in matches):
            reference["expected_document_ids"] = list(dict.fromkeys(ids[0] for ids in matches))
            values["reference"] = reference
        else:
            # Never guess for duplicate titles or mark unresolved labels as approved.
            values.update(reviewed_by=None, reviewed_at=None)
        connection.execute(examples.update().where(examples.c.id == row["id"]).values(**values))


def downgrade():
    # Keep additive JSON IDs and human audit history; older readers ignore the field.
    pass
