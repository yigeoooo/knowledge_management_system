"""One evaluation dataset per knowledge base, preserving examples and experiments.

Revision ID: e42b6c8d901a
Revises: d31f9a827c60
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "e42b6c8d901a"
down_revision = "d31f9a827c60"
branch_labels = depends_on = None


def merge_datasets(connection):
    metadata = sa.MetaData()
    datasets = sa.Table("evaluation_datasets", metadata, autoload_with=connection)
    examples = sa.Table("evaluation_examples", metadata, autoload_with=connection)
    runs = sa.Table("evaluation_runs", metadata, autoload_with=connection)
    audits = sa.Table("audit_logs", metadata, autoload_with=connection)
    groups = defaultdict(list)
    for row in connection.execute(
        sa.select(datasets).order_by(datasets.c.created_at, datasets.c.id)
    ).mappings():
        groups[row["knowledge_base_id"]].append(row)
    counts = dict(
        connection.execute(
            sa.select(examples.c.dataset_id, sa.func.count()).group_by(examples.c.dataset_id)
        ).all()
    )
    for base_id, group in groups.items():
        if len(group) < 2:
            continue
        # Prefer the most populated existing set; ties retain the oldest set.
        group.sort(key=lambda row: -counts.get(row["id"], 0))
        keep, others = group[0], group[1:]
        used = set(
            connection.scalars(
                sa.select(examples.c.name).where(examples.c.dataset_id == keep["id"])
            )
        )
        detail = {
            "knowledge_base_id": str(base_id),
            "retained_dataset_id": str(keep["id"]),
            "merged_datasets": [],
        }
        for old in others:
            record = {
                key: str(old[key]) if old[key] is not None else None
                for key in ("id", "name", "description", "created_by", "created_at")
            }
            moved = []
            for example in connection.execute(
                sa.select(examples)
                .where(examples.c.dataset_id == old["id"])
                .order_by(examples.c.id)
            ).mappings():
                name, serial = example["name"], 1
                while name in used:
                    suffix = f"（合并 {str(old['id'])[:8]}-{serial}）"
                    name = example["name"][: 200 - len(suffix)] + suffix
                    serial += 1
                used.add(name)
                connection.execute(
                    examples.update()
                    .where(examples.c.id == example["id"])
                    .values(dataset_id=keep["id"], name=name)
                )
                moved.append(
                    {"id": str(example["id"]), "original_name": example["name"], "name": name}
                )
            record["examples"] = moved
            record["run_ids"] = [
                str(value)
                for value in connection.scalars(
                    sa.select(runs.c.id).where(runs.c.dataset_id == old["id"])
                )
            ]
            # Do not rewrite frozen experimental inputs, results, or human reviews.
            connection.execute(
                runs.update().where(runs.c.dataset_id == old["id"]).values(dataset_id=keep["id"])
            )
            connection.execute(datasets.delete().where(datasets.c.id == old["id"]))
            detail["merged_datasets"].append(record)
        timestamp = datetime.now(UTC)
        # Reflected SQLite UUID columns are CHAR, PostgreSQL columns are native UUID.
        identifier = uuid4() if connection.dialect.name == "postgresql" else uuid4().hex
        connection.execute(
            audits.insert().values(
                id=identifier,
                user_id=None,
                action="evaluation.dataset.merge",
                resource_type="evaluation_datasets",
                resource_id=keep["id"],
                detail=detail,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                "LOCK TABLE evaluation_datasets, evaluation_examples, evaluation_runs IN ACCESS EXCLUSIVE MODE"
            )
        )
    merge_datasets(connection)
    with op.batch_alter_table("evaluation_datasets") as batch:
        batch.create_unique_constraint(
            "uq_evaluation_dataset_knowledge_base", ["knowledge_base_id"]
        )
    if connection.dialect.name == "postgresql":
        op.execute("COMMENT ON TABLE evaluation_datasets IS '每个知识库唯一的评测集。'")
        op.execute(
            "COMMENT ON COLUMN evaluation_datasets.knowledge_base_id IS '评测知识库，每个知识库最多一个评测集。'"
        )


def downgrade():
    # Merged content remains intact; splitting sets would invalidate later edits.
    with op.batch_alter_table("evaluation_datasets") as batch:
        batch.drop_constraint("uq_evaluation_dataset_knowledge_base", type_="unique")
