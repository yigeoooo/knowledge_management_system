"""Add managed robot identity and interaction prompts without changing prior versions."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "f73a20bd961e"
down_revision = "e42b6c8d901a"
branch_labels = depends_on = None


def upgrade():
    stamp = datetime.now(UTC)
    templates = sa.table("prompt_templates", sa.column("key", sa.String), sa.column("name", sa.String),
                         sa.column("active_version", sa.Integer), sa.column("generation", sa.Integer),
                         sa.column("updated_at", sa.DateTime))
    versions = sa.table("prompt_versions", sa.column("id", sa.Uuid), sa.column("prompt_key", sa.String),
                        sa.column("version", sa.Integer), sa.column("content", sa.Text), sa.column("note", sa.String),
                        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime))
    seeds = json.loads((Path(__file__).parents[1] / "data/robot-interaction-v1.json").read_text())
    op.bulk_insert(templates, [{"key": p["key"], "name": p["name"], "active_version": 1,
                                "generation": 1, "updated_at": stamp} for p in seeds])
    op.bulk_insert(versions, [{"id": UUID(p["id"]), "prompt_key": p["key"], "version": 1,
                               "content": p["content"], "note": "小维自然交流功能初始版本",
                               "created_at": stamp, "updated_at": stamp} for p in seeds])
    if op.get_context().dialect.name == "postgresql":
        op.execute("COMMENT ON COLUMN qa_logs.answer_kind IS 'knowledge 知识回答、clarification 澄清、chat 闲聊、general 通识、realtime 实时信息能力说明。'")


def downgrade():
    keys = "('robot_persona', 'robot_interaction')"
    op.execute(sa.text(f"DELETE FROM prompt_versions WHERE prompt_key IN {keys}"))
    op.execute(sa.text(f"DELETE FROM prompt_templates WHERE key IN {keys}"))
    if op.get_context().dialect.name == "postgresql":
        op.execute("COMMENT ON COLUMN qa_logs.answer_kind IS 'knowledge 知识回答或 clarification 澄清。'")
