"""Register the robot simulator page for administrators on existing installations."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "9b4f62a710cd"
down_revision = "6d8a2b1c904f"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
    # Empty databases receive all seed pages from init.sql after schema creation.
    admin_id = connection.scalar(sa.select(roles.c.id).where(roles.c.code == "super_admin"))
    if admin_id is None:
        return
    pages = sa.table(
        "pages",
        sa.column("id", sa.Uuid()),
        *[
            sa.column(name, sa.String())
            for name in (
                "code",
                "name",
                "route_path",
                "route_name",
                "component_key",
                "page_type",
                "status",
            )
        ],
        sa.column("sort_order", sa.Integer()),
        sa.column("is_visible", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    page_id = connection.scalar(sa.select(pages.c.id).where(pages.c.code == "robot_qa"))
    timestamp = datetime.now(UTC)
    if page_id is None:
        page_id = uuid4()
        connection.execute(
            pages.insert().values(
                id=page_id,
                code="robot_qa",
                name="机器人问答",
                route_path="/robot-qa",
                route_name="RobotQA",
                component_key="RobotQA",
                page_type="menu",
                sort_order=25,
                is_visible=True,
                status="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    permissions = sa.table(
        "role_page_permissions",
        sa.column("role_id", sa.Uuid()),
        sa.column("page_id", sa.Uuid()),
        sa.column("can_view", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    exists = connection.scalar(
        sa.select(permissions.c.role_id).where(
            permissions.c.role_id == admin_id,
            permissions.c.page_id == page_id,
        )
    )
    if exists is None:
        connection.execute(
            permissions.insert().values(
                role_id=admin_id,
                page_id=page_id,
                can_view=True,
                created_at=timestamp,
            )
        )


def downgrade():
    op.execute(
        "DELETE FROM role_page_permissions WHERE page_id IN "
        "(SELECT id FROM pages WHERE code = 'robot_qa')"
    )
    op.execute("DELETE FROM pages WHERE code = 'robot_qa'")
