from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from test_prompt_evaluations import admin as admin_fixture
from test_prompt_evaluations import approved_run, save
from test_prompt_evaluations import dataset as dataset_fixture

from app.core.extensions import db
from app.entities import (
    AuditLog,
    EvaluationDataset,
    EvaluationExample,
    EvaluationRun,
)

admin = admin_fixture
dataset = dataset_fixture


def test_dataset_unique_in_api_and_database(app, client, admin, dataset):
    did = dataset[0]
    sets = client.get('/api/v1/evaluations/datasets', headers=admin).json['data']['items']
    current = next(row for row in sets if row['id'] == did)
    assert current['knowledge_base_name'] == '评测资料'
    response = client.post('/api/v1/evaluations/datasets', headers=admin,
        json={'name': '另一套题', 'knowledge_base_id': current['knowledge_base_id']})
    assert response.status_code == 409 and '已有评测集' in response.json['message']
    options = client.get('/api/v1/evaluations/options', headers=admin).json['data']['knowledge_bases']
    assert next(b for b in options if b['id'] == current['knowledge_base_id'])['dataset_id'] == did
    empty = next(b for b in options if not b['dataset_id'])
    assert client.post('/api/v1/evaluations/datasets', headers=admin,
        json={'name': '其他知识库评测', 'knowledge_base_id': empty['id']}).status_code == 201
    with app.app_context():
        db.session.add(EvaluationDataset(name='绕过接口', knowledge_base_id=UUID(current['knowledge_base_id'])))
        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()


def test_new_enabled_question_invalidates_previous_acceptance(app, client, admin, dataset, monkeypatch):
    did, _, payload = dataset
    _, version = save(client, admin)
    run = approved_run(app, client, admin, dataset, monkeypatch, version['id'])
    endpoint = '/api/v1/prompts/answer_robot/versions/2/release-check'
    assert client.get(endpoint, headers=admin).json['data']['eligible']
    response = client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
        json={**payload, 'name': '新增草稿'})
    new = response.json['data']
    assert client.get(endpoint, headers=admin).json['data']['eligible']
    assert client.put(f'/api/v1/evaluations/examples/{new["id"]}', headers=admin,
        json={**payload, 'name': '新增草稿', 'status': 'enabled', 'expected_revision': 1}).status_code == 200
    result = client.get(endpoint, headers=admin).json['data']
    assert not result['eligible'] and any('全部已启用题目' in r for r in result['reasons'])
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin,
        json={'version': 2, 'expected_generation': 1, 'evaluation_run_id': run['id'], 'dataset_id': did}).status_code == 409


def test_release_uses_selected_base_unique_set_not_another_bases_result(app, client, admin, dataset, monkeypatch):
    _, version = save(client, admin)
    run = approved_run(app, client, admin, dataset, monkeypatch, version['id'])
    options = client.get('/api/v1/evaluations/options', headers=admin).json['data']['knowledge_bases']
    other = next(row for row in options if not row['dataset_id'])
    second = client.post('/api/v1/evaluations/datasets', headers=admin,
        json={'name': '另一个知识库', 'knowledge_base_id': other['id']}).json['data']['id']
    endpoint = '/api/v1/prompts/answer_robot/versions/2/release-check'
    unspecified = client.get(endpoint, headers=admin).json['data']
    assert not unspecified['eligible'] and len(unspecified['datasets']) == 2
    assert client.get(endpoint + f'?dataset_id={second}', headers=admin).json['data']['runs'] == []
    assert client.get(endpoint + f'?dataset_id={dataset[0]}', headers=admin).json['data']['eligible']
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin,
        json={'version': 2, 'expected_generation': 1, 'evaluation_run_id': run['id'], 'dataset_id': second}).status_code == 409
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin,
        json={'version': 2, 'expected_generation': 1, 'evaluation_run_id': run['id'], 'dataset_id': dataset[0]}).status_code == 200


def test_duplicate_migration_preserves_questions_frozen_runs_and_audit(app, dataset):
    result = app.test_cli_runner().invoke(args=['db', 'downgrade', 'd31f9a827c60'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        canonical = db.session.get(EvaluationDataset, UUID(dataset[0]))
        original = db.session.get(EvaluationExample, UUID(dataset[1]['id']))
        duplicate = EvaluationDataset(name='另一份旧评测集', description='旧用途说明', knowledge_base_id=canonical.knowledge_base_id)
        empty = EvaluationDataset(name='空评测集', knowledge_base_id=canonical.knowledge_base_id)
        db.session.add_all([duplicate, empty]); db.session.flush()
        copy = EvaluationExample(dataset_id=duplicate.id, name=original.name,
            inputs=deepcopy(original.inputs), reference=deepcopy(original.reference), revision=3)
        db.session.add(copy); db.session.flush()
        snapshot = {'dataset_name': duplicate.name, 'examples': [{'id': str(copy.id), 'name': copy.name}]}
        results = [{'id': str(copy.id), 'review': {'candidate': 1}}]
        run = EvaluationRun(dataset_id=duplicate.id, name='已有实验', status='COMPLETED', snapshot=snapshot, results=results)
        db.session.add(run); db.session.commit()
        base_id, original_id, copy_id, run_id = canonical.knowledge_base_id, original.id, copy.id, run.id
        duplicate_id = duplicate.id
        db.session.remove()
    result = app.test_cli_runner().invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        sets = db.session.scalars(db.select(EvaluationDataset).where(EvaluationDataset.knowledge_base_id == base_id)).all()
        assert len(sets) == 1 and str(sets[0].id) == dataset[0]
        original = db.session.get(EvaluationExample, original_id)
        copy = db.session.get(EvaluationExample, copy_id)
        assert copy.dataset_id == original.dataset_id and copy.name != original.name
        assert copy.inputs == original.inputs and copy.reference == original.reference and copy.revision == 3
        run = db.session.get(EvaluationRun, run_id)
        assert run.dataset_id == original.dataset_id and run.snapshot == snapshot and run.results == results
        audit = db.session.scalar(db.select(AuditLog).where(AuditLog.action == 'evaluation.dataset.merge'))
        assert audit.detail['retained_dataset_id'] == dataset[0].replace('-', '') or UUID(audit.detail['retained_dataset_id']) == UUID(dataset[0])
        merged = next(item for item in audit.detail['merged_datasets'] if UUID(item['id']) == duplicate_id)
        assert merged['description'] == '旧用途说明' and UUID(merged['run_ids'][0]) == run_id
