"""Reset prompt purposes to the explicitly requested seven fresh v1 versions."""
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "b94c0d523e18"
down_revision = "a83b9c412d07"
branch_labels = depends_on = None


def upgrade():
    op.add_column("robots", sa.Column("default_location_name", sa.String(300), comment="天气城市编号对应的可读地区名称。"))
    op.execute(sa.text("UPDATE robots SET default_location_name=default_location"))
    bind = op.get_bind()
    # Old experiment snapshots remain historical records; never reinterpret them
    # as validation of the fresh v1 identities. Pending work must be restarted.
    bind.execute(sa.text("UPDATE evaluation_runs SET status='FAILED', error_message='提示词已重置为新版v1，请重新创建实验', lease_token=NULL, lease_expires_at=NULL WHERE status IN ('PENDING','RUNNING')"))
    bind.execute(sa.text("UPDATE qa_logs SET status='FAILED', error_message='提示词已重置，请重新提问', lease_token=NULL, lease_expires_at=NULL WHERE status IN ('PENDING','PROCESSING')"))
    bind.execute(sa.text("DELETE FROM prompt_versions"))
    bind.execute(sa.text("DELETE FROM prompt_templates"))
    seeds = json.loads((Path(__file__).parents[1] / 'data/conversation-v3-v1.json').read_text())
    for p in seeds:
        bind.execute(sa.text("INSERT INTO prompt_templates (key,name,active_version,generation,archived,updated_at) VALUES (:key,:name,1,1,false,CURRENT_TIMESTAMP)"), p)
        bind.execute(sa.text("INSERT INTO prompt_versions (id,prompt_key,version,content,note,created_at,updated_at) VALUES (:id,:key,1,:content,'新版七用途初始v1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {**p, 'id': p['id'] if bind.dialect.name == 'postgresql' else p['id'].replace('-', '')})


def downgrade():
    raise RuntimeError("提示词重置不可自动回退，请使用重置前备份")
