"""Add reproducible index profiles and local RAG diagnostics."""
import sqlalchemy as sa
from alembic import op
revision = "b84d01e7f230"
down_revision = "9b4f62a710cd"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_versions", sa.Column("index_profile", sa.JSON(), comment="实际索引配置快照；旧索引为空。"))
    op.add_column("document_versions", sa.Column("index_config_hash", sa.String(64), comment="索引配置的 SHA256 摘要。"))
    op.add_column("qa_logs", sa.Column("execution_trace", sa.JSON(), comment="RAG 运行版本、阶段耗时、召回分数及 token 用量。"))


def downgrade():
    op.drop_column("qa_logs", "execution_trace")
    op.drop_column("document_versions", "index_config_hash")
    op.drop_column("document_versions", "index_profile")
