"""Describe the deleted user status without changing existing account data.

Revision ID: 52c7a3d910e6
Revises: 16bb29ab4421
"""

from alembic import op

revision = "52c7a3d910e6"
down_revision = "16bb29ab4421"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute(
            "COMMENT ON COLUMN users.status IS "
            "'用户状态：active 启用、disabled 停用、deleted 已逻辑删除；"
            "已删除用户不展示、不能登录，保留历史关联且用户名不复用。'"
        )


def downgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute(
            "COMMENT ON COLUMN users.status IS "
            "'业务启用状态：active 启用、disabled 停用；具体归档状态见所属表说明。'"
        )
