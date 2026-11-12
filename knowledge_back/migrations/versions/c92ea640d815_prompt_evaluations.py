"""Versioned prompts, human-reviewed test sets and paired experiments."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "c92ea640d815"
down_revision = "b84d01e7f230"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prompt_templates",
        sa.Column(
            "key", sa.String(length=64), nullable=False, primary_key=True, comment="稳定用途键。"
        ),
        sa.Column(
            "name", sa.String(length=100), nullable=False, primary_key=False, comment="展示名称。"
        ),
        sa.Column(
            "active_version",
            sa.Integer(),
            nullable=False,
            primary_key=False,
            comment="当前已发布版本号。",
        ),
        sa.Column(
            "generation",
            sa.Integer(),
            nullable=False,
            primary_key=False,
            comment="发布代数，用于并发检查。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录最后修改时间，带时区，应用更新时维护。",
        ),
        comment="提示词用途与当前发布版本。",
    )
    op.create_table(
        "prompt_versions",
        sa.Column(
            "prompt_key",
            sa.String(length=64),
            nullable=False,
            primary_key=False,
            comment="所属提示词用途。",
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, primary_key=False, comment="用途内递增版本号。"
        ),
        sa.Column(
            "content", sa.Text(), nullable=False, primary_key=False, comment="系统提示词正文。"
        ),
        sa.Column(
            "note", sa.String(length=1000), nullable=False, primary_key=False, comment="修改说明。"
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            nullable=True,
            primary_key=False,
            comment="创建此记录的用户 ID，关联 users.id；系统初始化时可为空。",
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            primary_key=True,
            comment="记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录创建时间，带时区，应用统一使用 UTC。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录最后修改时间，带时区，应用更新时维护。",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["prompt_key"], ["prompt_templates.key"]),
        sa.UniqueConstraint("prompt_key", "version", name="uq_prompt_version"),
        comment="不可变提示词版本；保存草稿产生新版本。",
    )
    op.create_table(
        "evaluation_datasets",
        sa.Column(
            "name", sa.String(length=200), nullable=False, primary_key=False, comment="评测集名称。"
        ),
        sa.Column(
            "knowledge_base_id",
            sa.Uuid(),
            nullable=False,
            primary_key=False,
            comment="评测知识库。",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            primary_key=False,
            comment="供管理人员阅读的用途或业务描述，可为空。",
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            nullable=True,
            primary_key=False,
            comment="创建此记录的用户 ID，关联 users.id；系统初始化时可为空。",
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            primary_key=True,
            comment="记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录创建时间，带时区，应用统一使用 UTC。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录最后修改时间，带时区，应用更新时维护。",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        comment="管理员维护的评测集。",
    )
    op.create_table(
        "evaluation_examples",
        sa.Column(
            "dataset_id", sa.Uuid(), nullable=False, primary_key=False, comment="所属评测集。"
        ),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
            primary_key=False,
            comment="集内唯一名称。",
        ),
        sa.Column(
            "inputs",
            sa.JSON(),
            nullable=False,
            primary_key=False,
            comment="问题、历史语境与机器人标志。",
        ),
        sa.Column(
            "reference",
            sa.JSON(),
            nullable=False,
            primary_key=False,
            comment="预期文档、答案要点与状态。",
        ),
        sa.Column(
            "revision", sa.Integer(), nullable=False, primary_key=False, comment="内容修订号。"
        ),
        sa.Column(
            "reviewed_by", sa.Uuid(), nullable=True, primary_key=False, comment="人工审核人。"
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            primary_key=False,
            comment="人工审核时间。",
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            nullable=True,
            primary_key=False,
            comment="创建此记录的用户 ID，关联 users.id；系统初始化时可为空。",
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            primary_key=True,
            comment="记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录创建时间，带时区，应用统一使用 UTC。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录最后修改时间，带时区，应用更新时维护。",
        ),
        sa.UniqueConstraint("dataset_id", "name", name="uq_evaluation_example"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluation_datasets.id"]),
        comment="评测题目及人工参考标注，编辑后需重新审核。",
    )
    op.create_index("ix_evaluation_examples_dataset_id", "evaluation_examples", ["dataset_id"])
    op.create_table(
        "evaluation_runs",
        sa.Column(
            "dataset_id", sa.Uuid(), nullable=False, primary_key=False, comment="来源评测集。"
        ),
        sa.Column(
            "name", sa.String(length=200), nullable=False, primary_key=False, comment="实验名称。"
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            primary_key=False,
            comment="PENDING、RUNNING、COMPLETED 或 FAILED。",
        ),
        sa.Column(
            "snapshot",
            sa.JSON(),
            nullable=False,
            primary_key=False,
            comment="测试题、提示词、索引和运行配置快照。",
        ),
        sa.Column(
            "results",
            sa.JSON(),
            nullable=False,
            primary_key=False,
            comment="逐题基线与候选答案、指标和人工评分。",
        ),
        sa.Column(
            "error_message",
            sa.String(length=500),
            nullable=True,
            primary_key=False,
            comment="操作失败的可读原因；不得写入密钥或密码。",
        ),
        sa.Column(
            "lease_token", sa.Uuid(), nullable=True, primary_key=False, comment="任务执行令牌。"
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            primary_key=False,
            comment="租约到期时间。",
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, primary_key=False, comment="执行尝试次数。"
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            nullable=True,
            primary_key=False,
            comment="创建此记录的用户 ID，关联 users.id；系统初始化时可为空。",
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
            primary_key=True,
            comment="记录主键，UUID 格式，由应用生成；初始化数据由 SQL 生成。",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录创建时间，带时区，应用统一使用 UTC。",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            primary_key=False,
            comment="记录最后修改时间，带时区，应用更新时维护。",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluation_datasets.id"]),
        comment="固定输入及提示词快照的成对评测任务。",
    )
    op.create_index("ix_evaluation_pending", "evaluation_runs", ["status", "lease_expires_at"])
    op.add_column(
        "qa_logs",
        sa.Column(
            "prompt_snapshot", sa.JSON(), comment="本轮使用的不可变提示词版本与正文快照，重试复用。"
        ),
    )
    stamp = datetime.now(UTC)
    templates = sa.table(
        "prompt_templates",
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("active_version", sa.Integer),
        sa.column("generation", sa.Integer),
        sa.column("updated_at", sa.DateTime),
    )
    versions = sa.table(
        "prompt_versions",
        sa.column("id", sa.Uuid),
        sa.column("prompt_key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("content", sa.Text),
        sa.column("note", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    seeds = json.loads((Path(__file__).parents[1] / "data/prompts-v1.json").read_text())
    op.bulk_insert(
        templates,
        [
            {"key": p["key"], "name": p["name"], "active_version": 1, "generation": 1, "updated_at": stamp}
            for p in seeds
        ],
    )
    op.bulk_insert(
        versions,
        [
            {
                "id": UUID(p["id"]),
                "prompt_key": p["key"],
                "version": 1,
                "content": p["content"],
                "note": "从原有代码迁移的初始版本",
                "created_at": stamp,
                "updated_at": stamp,
            }
            for p in seeds
        ],
    )
    for code, name, route, component, order in [
        ("prompts", "提示词管理", "/prompts", "PromptManagement", 91),
        ("evaluations", "质量评测", "/evaluations", "EvaluationManagement", 92),
    ]:
        # A fresh database gets its pages from init.sql after the migrations.
        op.execute(
            sa.text(
                "INSERT INTO pages (id, code, name, route_path, route_name, component_key, page_type, sort_order, is_visible, status, created_at, updated_at) SELECT "
                + (
                    "gen_random_uuid()"
                    if op.get_context().dialect.name == "postgresql"
                    else "lower(hex(randomblob(16)))"
                )
                + f", '{code}', '{name}', '{route}', '{component}', '{component}', 'menu', {order}, true, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP WHERE EXISTS (SELECT 1 FROM roles) AND NOT EXISTS (SELECT 1 FROM pages WHERE code='{code}')"
            )
        )
    op.execute(
        sa.text(
            "INSERT INTO role_page_permissions (role_id, page_id, can_view, created_at) SELECT r.id, p.id, true, CURRENT_TIMESTAMP FROM roles r CROSS JOIN pages p WHERE r.code='super_admin' AND p.code IN ('prompts','evaluations') AND NOT EXISTS (SELECT 1 FROM role_page_permissions x WHERE x.role_id=r.id AND x.page_id=p.id)"
        )
    )


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM role_page_permissions WHERE page_id IN (SELECT id FROM pages WHERE code IN ('prompts','evaluations'))"
        )
    )
    op.execute(sa.text("DELETE FROM pages WHERE code IN ('prompts','evaluations')"))
    op.drop_column("qa_logs", "prompt_snapshot")
    for table in (
        "evaluation_runs",
        "evaluation_examples",
        "evaluation_datasets",
        "prompt_versions",
        "prompt_templates",
    ):
        op.drop_table(table)
