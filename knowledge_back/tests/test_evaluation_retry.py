from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from test_knowledge_bases import login
from test_prompt_evaluations import admin as admin_fixture
from test_prompt_evaluations import dataset as dataset_fixture
from test_prompt_evaluations import save

from app.application.prompts.registry import get_prompt
from app.core.extensions import db
from app.entities import DocumentVersion, EvaluationRun, KnowledgeBase, PromptTemplate, now
from app.integrations.ai.chat_adapter import ChatError
from app.workers import evaluation_worker

admin = admin_fixture
dataset = dataset_fixture


@pytest.mark.parametrize('single', [False, True])
def test_retry_keeps_both_historical_prompt_sets_and_context(app, client, admin, dataset, monkeypatch, single):
    did, example, payload = dataset
    history = {'turns': [{'question': '我们有8个人', 'answer': '请问想去哪里？'}]}
    example = client.put(f"/api/v1/evaluations/examples/{example['id']}", headers=admin, json={
        **payload, 'inputs': {**payload['inputs'], 'context': history}, 'expected_revision': 1,
    }).json['data']
    before, published = save(client, admin)
    historical = before['versions'][0]
    with app.app_context():
        db.session.get(PromptTemplate, 'answer_robot').active_version = published['version']
        db.session.commit()
    request = {'dataset_id': did, 'name': '历史版本对比', 'reviewed_only': False,
               'overrides': {'answer_robot': historical['id']}}
    if single:
        request.update(example_id=example['id'], expected_revision=example['revision'])
    original = client.post('/api/v1/evaluations/runs', headers=admin, json=request).json['data']
    seen = []

    def fail(inputs, **kwargs):
        seen.append(get_prompt('answer_robot'))
        raise ChatError('问答模型连接超时，请稍后重试')

    monkeypatch.setattr(evaluation_worker, 'evaluate_input', fail)
    assert evaluation_worker.process_one(app)
    assert seen == [published['content'], historical['content']]
    original = client.get(f"/api/v1/evaluations/runs/{original['id']}", headers=admin).json['data']
    assert original['status'] == 'FAILED'
    assert original['prompt_details'][historical['id']]['name'] == '机器人简洁回答'
    assert original['prompt_details'][published['id']]['note'] == '测试版本'
    # Publication and question edits must not replace the original prompts/history.
    with app.app_context():
        db.session.get(PromptTemplate, 'answer_robot').active_version = historical['version']
        db.session.commit()
    assert client.put(f"/api/v1/evaluations/examples/{example['id']}", headers=admin, json={
        **payload, 'inputs': {**payload['inputs'], 'question': '改后的问题'},
        'expected_revision': example['revision'],
    }).status_code == 200
    response = client.post(f"/api/v1/evaluations/runs/{original['id']}/retry", headers=admin)
    assert response.status_code == 202, response.json
    retried = response.json['data']
    assert retried['id'] == original['id'] and retried['status'] == 'PENDING'
    assert retried['scope'] == ('single' if single else 'dataset')
    assert retried['completed'] == 0 and retried['summary']['human_reviewed_count'] == 0
    detail = client.get(f"/api/v1/evaluations/runs/{retried['id']}", headers=admin).json['data']
    for key in ('baseline', 'candidate', 'examples', 'dataset_hash', 'reviewed_only'):
        assert detail['snapshot'][key] == original['snapshot'][key]
    assert detail['snapshot'] == original['snapshot']
    # A repeated click cannot queue concurrent work for the same record.
    assert client.post(f"/api/v1/evaluations/runs/{original['id']}/retry", headers=admin).status_code == 409
    calls = []

    def evaluate(inputs, **kwargs):
        calls.append((deepcopy(inputs), get_prompt('answer_robot')))
        return {'answer': '99元', 'status': 'SUCCESS'}

    monkeypatch.setattr(evaluation_worker, 'evaluate_input', evaluate)
    assert evaluation_worker.process_one(app)
    assert [p for _, p in calls] == [published['content'], historical['content']]
    assert all(i['context'] == history and i['question'] == payload['inputs']['question'] for i, _ in calls)
    final = client.get(f"/api/v1/evaluations/runs/{retried['id']}", headers=admin).json['data']
    assert final['status'] == 'COMPLETED'
    assert final['summary']['human_reviewed_count'] == 0
    assert len(client.get('/api/v1/evaluations/runs', headers=admin).json['data']['items']) == 1


def test_retry_rejects_nonfailed_runs_and_inactive_base(client, app, admin, dataset):
    did, _, _ = dataset
    run = client.post('/api/v1/evaluations/runs', headers=admin, json={
        'dataset_id': did, 'name': '重试边界', 'reviewed_only': False,
    }).json['data']
    endpoint = f"/api/v1/evaluations/runs/{run['id']}/retry"
    assert client.post(endpoint, headers=admin).status_code == 409
    with app.app_context():
        row = db.session.get(EvaluationRun, UUID(run['id']))
        row.status = 'FAILED'
        db.session.get(KnowledgeBase, UUID(row.snapshot['knowledge_base_id'])).status = 'disabled'
        db.session.commit()
    assert client.post(endpoint, headers=admin).status_code == 409
    assert client.post(f'/api/v1/evaluations/runs/{uuid4()}/retry', headers=admin).status_code == 404
    assert client.post(endpoint).status_code == 401
    result = app.test_cli_runner().invoke(args=['create-user', '--username', 'retry-reader'],
        input='Reader-Password-2026!\nReader-Password-2026!\n')
    assert result.exit_code == 0
    reader = login(client, 'retry-reader', 'Reader-Password-2026!')
    assert client.post(endpoint, headers=reader).status_code == 403


def test_model_failure_keeps_safe_reason_and_trace_id(app, monkeypatch):
    def fail(*args, **kwargs):
        error = ChatError('问答模型连接超时，请稍后重试')
        error.execution_trace = {'run_id': 'trace-id', 'prompts': {'answer_robot': {'version': 1}}}
        raise error
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', fail)
    with app.app_context():
        result = evaluation_worker.evaluate_arm({'inputs': {}, 'reference': {}}, {})
    assert result['error'] == 'ChatError'
    assert result['error_message'] == '问答模型连接超时，请稍后重试'
    assert result['outputs']['run_id'] == 'trace-id'
    assert result['outputs']['prompt_versions'] == {'answer_robot': {'version': 1}}

    def unsafe(*args, **kwargs):
        raise ValueError('private-provider-body')
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', unsafe)
    with app.app_context():
        result = evaluation_worker.evaluate_arm({'inputs': {}, 'reference': {}}, {})
    assert 'private-provider-body' not in str(result)


@pytest.mark.parametrize('retry_all', [False, True])
def test_retry_updates_only_requested_failures_and_preserves_successful_answers_and_reviews(app, client, admin, dataset, monkeypatch, retry_all):
    did, first, payload = dataset
    samples = [first]
    for name in ('异常一', '异常二'):
        samples.append(client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
            json={**payload, 'name': name}).json['data'])
    run = client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '保留正常结果', 'reviewed_only': False}).json['data']
    failed_ids = {s['id'] for s in samples[1:]}
    calls = []
    def evaluate(inputs, *, trace_context):
        calls.append((trace_context['evaluation_example_id'], trace_context['evaluation_arm']))
        if trace_context['evaluation_example_id'] in failed_ids and trace_context['evaluation_arm'] == 'baseline':
            raise ChatError('问答模型连接超时，请稍后重试')
        return {'answer': '99元', 'status': 'SUCCESS'}
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', evaluate)
    assert evaluation_worker.process_one(app)
    assert client.post(f"/api/v1/evaluations/runs/{run['id']}/reviews/{first['id']}",
        headers=admin, json={'candidate': 1, 'note': '已核实'}).status_code == 200
    original = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    endpoint = f"/api/v1/evaluations/runs/{run['id']}/retry"
    assert client.post(endpoint, headers=admin, json={'example_id': first['id']}).status_code == 409
    assert client.post(endpoint, headers=admin, json={'example_id': str(uuid4())}).status_code == 404
    for invalid in (None, '', True, 'bad-id'):
        assert client.post(endpoint, headers=admin, json={'example_id': invalid}).status_code == 422
    selected = set(failed_ids) if retry_all else {samples[1]['id']}
    response = client.post(endpoint, headers=admin, json={} if retry_all else {'example_id': samples[1]['id']})
    assert response.status_code == 202, response.json
    queued = response.json['data']
    assert queued['id'] == run['id'] and queued['name'] == run['name']
    assert queued['completed'] == 3 - len(selected)
    assert queued['summary']['human_reviewed_count'] == 1
    assert queued['results'][0] == original['results'][0]
    assert {r['id'] for r in queued['results'] if r.get('retry_pending')} == selected
    assert client.post(endpoint, headers=admin).status_code == 409
    failed_ids.clear()
    calls.clear()
    assert evaluation_worker.process_one(app)
    assert set(calls) == {(id, 'baseline') for id in selected}
    result = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    assert result['snapshot'] == original['snapshot']
    assert result['status'] == ('COMPLETED' if retry_all else 'FAILED')
    assert result['results'][0] == original['results'][0]
    for before, after in zip(original['results'], result['results'], strict=True):
        assert before['candidate'] == after['candidate']
        if before['id'] not in selected:
            assert before == after
    assert result['summary']['human_reviewed_count'] == 1
    assert len(client.get('/api/v1/evaluations/runs', headers=admin).json['data']['items']) == 1


@pytest.mark.parametrize('interrupted_after', [1, 2])
def test_retry_recovers_checkpoints_without_running_other_missing_questions(app, client, admin, dataset, monkeypatch, interrupted_after):
    did, first, payload = dataset
    second = client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
        json={**payload, 'name': '另一道未生成题目'}).json['data']
    run = client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '中断恢复', 'reviewed_only': False}).json['data']
    with app.app_context():
        row = db.session.get(EvaluationRun, UUID(run['id']))
        row.status, row.attempts, row.error_message = 'FAILED', 3, '评测多次中断'
        db.session.commit()
    endpoint = f"/api/v1/evaluations/runs/{run['id']}/retry"
    response = client.post(endpoint, headers=admin, json={'example_id': first['id']})
    assert response.status_code == 202, response.json
    assert [r['id'] for r in response.json['data']['results']] == [first['id']]
    calls = []

    def evaluate(inputs, *, trace_context):
        calls.append((trace_context['evaluation_example_id'], trace_context['evaluation_arm']))
        return {'answer': '99元', 'status': 'SUCCESS'}

    update = evaluation_worker.update
    checkpoints = 0

    def interrupt_after_checkpoint(id, token, **values):
        nonlocal checkpoints
        success = update(id, token, **values)
        if 'results' in values:
            checkpoints += 1
            if checkpoints == interrupted_after:
                # Simulate a stopped worker after a durable checkpoint; recovery
                # must neither repeat that arm nor pick an unselected question.
                row = db.session.get(EvaluationRun, id)
                row.lease_expires_at = now() - timedelta(seconds=1)
                db.session.commit()
                return False
        return success

    monkeypatch.setattr(evaluation_worker, 'evaluate_input', evaluate)
    monkeypatch.setattr(evaluation_worker, 'update', interrupt_after_checkpoint)
    assert evaluation_worker.process_one(app)
    assert len(calls) == interrupted_after
    assert evaluation_worker.process_one(app)
    assert calls == [(first['id'], 'baseline'), (first['id'], 'candidate')]
    result = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    assert result['status'] == 'FAILED' and result['completed'] == 1
    assert result['results'][0]['retry_pending'] == []
    assert len(result['results']) == 1
    assert client.post(endpoint, headers=admin, json={'example_id': first['id']}).status_code == 409
    assert client.post(endpoint, headers=admin).status_code == 202
    calls.clear()
    assert evaluation_worker.process_one(app)
    assert set(calls) == {(second['id'], 'baseline'), (second['id'], 'candidate')}
    final = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    assert final['status'] == 'COMPLETED' and final['completed'] == 2
    assert final['results'][0] == result['results'][0]
    assert len(client.get('/api/v1/evaluations/runs', headers=admin).json['data']['items']) == 1


def test_retry_cannot_mix_changed_index_with_preserved_results(app, client, admin, dataset, monkeypatch):
    did, _, _ = dataset
    run = client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '环境变化', 'reviewed_only': False}).json['data']
    def fail(*args, **kwargs):
        raise ChatError('问答模型连接超时，请稍后重试')
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', fail)
    assert evaluation_worker.process_one(app)
    original = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    with app.app_context():
        version = db.session.scalar(db.select(DocumentVersion).where(DocumentVersion.minio_object_key == 'price'))
        version.index_config_hash = 'changed'
        db.session.commit()
    response = client.post(f"/api/v1/evaluations/runs/{run['id']}/retry", headers=admin)
    assert response.status_code == 409 and '索引' in response.json['message']
    assert client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data'] == original


@pytest.mark.parametrize('edit_after_failure', [False, True])
def test_retry_requires_fresh_review_and_current_dataset_for_publication(app, client, admin, dataset, monkeypatch, edit_after_failure):
    did, example, payload = dataset
    _, candidate = save(client, admin)
    assert client.post(f"/api/v1/evaluations/examples/{example['id']}/review", headers=admin,
        json={'expected_revision': 1, 'confirmed': True}).status_code == 200
    source = client.post('/api/v1/evaluations/runs', headers=admin, json={
        'dataset_id': did, 'name': '发布验收重测', 'overrides': {'answer_robot': candidate['id']},
    }).json['data']
    def fail(*args, **kwargs):
        raise ChatError('问答模型连接超时，请稍后重试')
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', fail)
    assert evaluation_worker.process_one(app)
    if edit_after_failure:
        assert client.put(f"/api/v1/evaluations/examples/{example['id']}", headers=admin,
            json={**payload, 'name': '新修订的题目', 'status': 'enabled', 'expected_revision': 1}).status_code == 200
    retry = client.post(f"/api/v1/evaluations/runs/{source['id']}/retry", headers=admin).json['data']
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', lambda *args, **kwargs: {'answer': '99元', 'status': 'SUCCESS'})
    assert evaluation_worker.process_one(app)
    publish = {'version': candidate['version'], 'expected_generation': 1, 'dataset_id': did, 'evaluation_run_id': retry['id']}
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin, json=publish).status_code == 409
    assert client.post(f"/api/v1/evaluations/runs/{retry['id']}/reviews/{example['id']}",
        headers=admin, json={'candidate': 1}).status_code == 200
    response = client.post('/api/v1/prompts/answer_robot/publish', headers=admin, json=publish)
    assert response.status_code == (409 if edit_after_failure else 200), response.json
