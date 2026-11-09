"""Add owned conversations, robot bindings, and durable answer jobs."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "6d8a2b1c904f"
down_revision = "52c7a3d910e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("robots") as batch:
        batch.add_column(sa.Column("knowledge_base_id", sa.Uuid()))
        batch.add_column(
            sa.Column("binding_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_foreign_key(
            "fk_robot_knowledge_base", "knowledge_bases", ["knowledge_base_id"], ["id"]
        )
    op.create_table(
        "qa_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("robot_id", sa.Uuid(), sa.ForeignKey("robots.id")),
        sa.Column(
            "knowledge_base_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), nullable=False
        ),
        sa.Column("robot_binding_version", sa.Integer()),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("creation_request_id", sa.String(100), nullable=False),
        sa.Column("next_turn_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_reason", sa.String(100)),
        sa.Column("memory_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary_through_turn_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memory_version", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "(source_type = 'WEB' AND user_id IS NOT NULL AND robot_id IS NULL) OR (source_type = 'ROBOT' AND robot_id IS NOT NULL AND user_id IS NULL)",
            name="ck_conversation_owner",
        ),
        sa.UniqueConstraint("user_id", "creation_request_id", name="uq_conversation_user_request"),
        sa.UniqueConstraint(
            "robot_id", "creation_request_id", name="uq_conversation_robot_request"
        ),
    )
    op.create_index(
        "ix_conversation_user_history",
        "qa_conversations",
        ["user_id", "deleted_at", "last_message_at", "id"],
    )
    op.create_index(
        "ix_conversation_robot_history", "qa_conversations", ["robot_id", "last_message_at", "id"]
    )
    with op.batch_alter_table("qa_logs") as batch:
        batch.add_column(sa.Column("conversation_id", sa.Uuid()))
        batch.add_column(sa.Column("turn_no", sa.Integer()))
        batch.add_column(sa.Column("resolved_question", sa.Text()))
        batch.add_column(
            sa.Column("answer_kind", sa.String(30), nullable=False, server_default="knowledge")
        )
        batch.add_column(sa.Column("context_snapshot", sa.JSON()))
        batch.add_column(sa.Column("lease_token", sa.Uuid()))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("suggestion_anchor", sa.String(36)))
        batch.create_foreign_key(
            "fk_qa_conversation", "qa_conversations", ["conversation_id"], ["id"]
        )
        batch.create_unique_constraint("uq_conversation_turn", ["conversation_id", "turn_no"])
    op.create_index("ix_qa_pending", "qa_logs", ["status", "lease_expires_at", "created_at"])
    predicate = sa.text("status IN ('PENDING', 'PROCESSING') AND conversation_id IS NOT NULL")
    op.create_index(
        "uq_conversation_inflight",
        "qa_logs",
        ["conversation_id"],
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )
    if op.get_context().dialect.name == "postgresql":
        from app.schema_comments import COMMON, SCHEMA

        for table in ("robots", "qa_conversations", "qa_logs"):
            description, fields = SCHEMA[table]
            op.execute(
                sa.text(
                    f"COMMENT ON TABLE {table} IS '{description.replace(chr(39), chr(39) * 2)}'"
                )
            )
            for column, description in fields.items():
                op.execute(
                    sa.text(
                        f"COMMENT ON COLUMN {table}.{column} IS '{description.replace(chr(39), chr(39) * 2)}'"
                    )
                )
        for column in ("id", "created_at", "updated_at", "user_id"):
            op.execute(
                sa.text(f"COMMENT ON COLUMN qa_conversations.{column} IS '{COMMON[column]}'")
            )
    if op.get_context().as_sql:
        # The offline output initializes empty installations; there are no rows to backfill.
        return
    # Preserve other installations' historical records; this deployment's explicit
    # cleanup is performed separately, never hidden inside a schema migration.
    connection = op.get_bind()
    metadata = sa.MetaData()
    logs = sa.Table("qa_logs", metadata, autoload_with=connection)
    conversations = sa.Table("qa_conversations", metadata, autoload_with=connection)
    for row in connection.execute(sa.select(logs)).mappings().all():
        owner = row["user_id"] if row["source_type"] == "WEB" else row["robot_id"]
        if owner is None or row["source_type"] not in {"WEB", "ROBOT"}:
            continue
        cid = uuid4()
        connection.execute(
            conversations.insert().values(
                id=cid,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_type=row["source_type"],
                user_id=row["user_id"] if row["source_type"] == "WEB" else None,
                robot_id=row["robot_id"] if row["source_type"] == "ROBOT" else None,
                knowledge_base_id=row["knowledge_base_id"],
                title=row["question"][:80],
                creation_request_id=row["request_id"],
                next_turn_no=2,
                last_message_at=row["created_at"],
                closed_at=row["updated_at"] if row["source_type"] == "ROBOT" else None,
                closed_reason="legacy_import" if row["source_type"] == "ROBOT" else None,
            )
        )
        values = {"conversation_id": cid, "turn_no": 1}
        if row["status"] == "PROCESSING":
            values.update(status="FAILED", error_message="系统升级中断了本次请求，请重新提问")
        connection.execute(logs.update().where(logs.c.id == row["id"]).values(**values))


def downgrade():
    op.drop_index("uq_conversation_inflight", table_name="qa_logs")
    op.drop_index("ix_qa_pending", table_name="qa_logs")
    with op.batch_alter_table("qa_logs") as batch:
        batch.drop_constraint("fk_qa_conversation", type_="foreignkey")
        batch.drop_constraint("uq_conversation_turn", type_="unique")
        for name in (
            "suggestion_anchor",
            "attempts",
            "lease_expires_at",
            "lease_token",
            "context_snapshot",
            "answer_kind",
            "resolved_question",
            "turn_no",
            "conversation_id",
        ):
            batch.drop_column(name)
    op.drop_table("qa_conversations")
    with op.batch_alter_table("robots") as batch:
        batch.drop_constraint("fk_robot_knowledge_base", type_="foreignkey")
        batch.drop_column("binding_version")
        batch.drop_column("knowledge_base_id")
