"""Validate the actual deployment bootstrap in a disposable PostgreSQL schema."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text

from app import create_app
from app.core.config import configuration
from app.extensions import db

pytestmark = pytest.mark.skipif(os.getenv('KBS_POSTGRES_TESTS') != '1', reason='explicit PostgreSQL integration run')


def test_init_sql_is_current_and_followup_upgrade_is_safe():
    schema = 'kbs_init_test_' + uuid4().hex
    url = configuration({'JWT_SECRET_KEY': 'isolated-bootstrap-test-secret-2026'})['SQLALCHEMY_DATABASE_URI']
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    app = create_app({'TESTING': True, 'LANGSMITH_TRACING': False, 'SQLALCHEMY_DATABASE_URI': url,
        'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': {'options': f'-c search_path={schema},public'}},
        'QA_WORKER_AUTOSTART': False, 'INDEX_WORKER_AUTOSTART': False})
    try:
        with app.app_context():
            assert db.session.scalar(text('SELECT current_schema()')) == schema
            db.session.rollback()
            sql = (Path(__file__).parents[2] / 'init.sql').read_text()
            with db.engine.connect() as connection:
                connection.exec_driver_sql(sql)
                connection.commit()
            assert db.session.scalar(text('SELECT version_num FROM alembic_version')) == 'e42b6c8d901a'
            inspector = inspect(db.engine)
            assert any(c['column_names'] == ['knowledge_base_id'] for c in inspector.get_unique_constraints('evaluation_datasets', schema=schema))
            for table, expected in {'qa_logs': {'execution_trace': 'JSON'},
                                    'document_versions': {'index_profile': 'JSON', 'index_config_hash': 'VARCHAR(64)'}}.items():
                columns = {c['name']: c for c in inspector.get_columns(table, schema=schema)}
                for name, data_type in expected.items():
                    assert str(columns[name]['type']) == data_type
                    assert columns[name]['nullable'] and columns[name]['comment']
            assert db.session.scalar(text("SELECT count(*) FROM pages WHERE route_path='/robot-qa'")) == 1
            assert db.session.scalar(text("SELECT count(*) FROM users WHERE username='root'")) == 1
        result = app.test_cli_runner().invoke(args=['db', 'upgrade'])
        assert result.exit_code == 0, result.output
        with app.app_context():
            assert db.session.scalar(text('SELECT version_num FROM alembic_version')) == 'e42b6c8d901a'
        # Also exercise the upgrade against real duplicate PostgreSQL data.
        result = app.test_cli_runner().invoke(args=['db', 'downgrade', 'd31f9a827c60'])
        assert result.exit_code == 0, result.output
        with app.app_context():
            from app.entities import (
                EvaluationDataset,
                EvaluationExample,
                EvaluationRun,
                KnowledgeBase,
            )
            base = db.session.scalar(db.select(KnowledgeBase))
            one = EvaluationDataset(name='首个评测集', knowledge_base_id=base.id)
            two = EvaluationDataset(name='重复评测集', knowledge_base_id=base.id)
            db.session.add_all([one, two]); db.session.flush()
            for dataset in (one, two):
                db.session.add(EvaluationExample(dataset_id=dataset.id, name='同名题目',
                    inputs={'question': '原始问题'}, reference={'answer_points': ['保留答案']}))
            run = EvaluationRun(dataset_id=two.id, name='旧实验', snapshot={'dataset_name': two.name},
                                results=[{'original': True}], status='COMPLETED')
            db.session.add(run); db.session.commit()
            run_id = run.id
            db.session.remove()
        result = app.test_cli_runner().invoke(args=['db', 'upgrade'])
        assert result.exit_code == 0, result.output
        with app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(EvaluationDataset)) == 1
            examples = db.session.scalars(db.select(EvaluationExample)).all()
            assert len(examples) == 2 and len({row.name for row in examples}) == 2
            run = db.session.get(EvaluationRun, run_id)
            assert run.snapshot == {'dataset_name': '重复评测集'} and run.results == [{'original': True}]
            assert run.dataset_id == examples[0].dataset_id == examples[1].dataset_id
            assert any(c['column_names'] == ['knowledge_base_id'] for c in inspect(db.engine).get_unique_constraints('evaluation_datasets', schema=schema))
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
