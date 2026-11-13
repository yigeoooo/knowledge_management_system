"""Candidate prompt protocol and explicit robot location; no automatic publication."""
import sqlalchemy as sa
from alembic import op

revision = "a83b9c412d07"
down_revision = "f73a20bd961e"
branch_labels = depends_on = None


def upgrade():
    op.add_column("prompt_templates", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false(), comment="历史用途归档标记；保留原版本。"))
    op.add_column("robots", sa.Column("default_location", sa.String(200), comment="管理员明确配置的默认查询地点，可为空。"))
    op.add_column("robots", sa.Column("timezone", sa.String(100), comment="管理员配置的 IANA 时区，可为空。"))


def downgrade():
    op.drop_column("robots", "timezone")
    op.drop_column("robots", "default_location")
    op.drop_column("prompt_templates", "archived")
