from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from test_prompt_evaluations import admin as admin_fixture
from test_prompt_evaluations import approved_run, save
from test_prompt_evaluations import dataset as dataset_fixture

from app.application.prompts.registry import get_prompt
from app.core.extensions import db
from app.entities import EvaluationRun
from app.workers import evaluation_worker

admin = admin_fixture
dataset = dataset_fixture


def single_request(dataset, **changes):
    did, example, _ = dataset
    return {'dataset_id': did, 'example_id': example['id'],
            'expected_revision': example['revision'], 'name': '单题测试', **changes}


@pytest.mark.parametrize('enabled', [False, True])
def test_single_question_freezes_only_selected_sample_and_runs_both_versions(app, client, admin, dataset, monkeypatch, enabled):
    did, example, payload = dataset
    if enabled:
        assert client.post(f"/api/v1/evaluations/examples/{example['id']}/review", headers=admin,
            json={'expected_revision': 1, 'confirmed': True}).status_code == 200
    other = client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
        json={**payload, 'name': '其他问题'}).json['data']
    _, candidate = save(client, admin)
    response = client.post('/api/v1/evaluations/runs', headers=admin,
        json=single_request(dataset, reviewed_only=True, overrides={'answer_robot': candidate['id']}))
    assert response.status_code == 202, response.json
    run = response.json['data']
    assert run['scope'] == 'single' and run['total'] == 1 and run['completed'] == 0
    assert run['reviewed_only'] is False
    # Further edits cannot change the saved input of the queued single-question run.
    changed = client.put(f"/api/v1/evaluations/examples/{example['id']}", headers=admin,
        json={**payload, 'inputs': {**payload['inputs'], 'question': '改后的问题'}, 'expected_revision': 1})
    assert changed.status_code == 200
    calls = []
    def evaluate(inputs, **kwargs):
        calls.append((deepcopy(inputs), get_prompt('answer_robot'), kwargs['trace_context']))
        return {'answer': '票价99元', 'status': 'SUCCESS'}
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', evaluate)
    assert evaluation_worker.process_one(app)
    detail = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    assert detail['status'] == 'COMPLETED' and detail['completed'] == detail['total'] == 1
    assert [e['id'] for e in detail['snapshot']['examples']] == [example['id']]
    assert [r['id'] for r in detail['results']] == [example['id']]
    assert len(calls) == 2 and all(call[0]['question'] == payload['inputs']['question'] for call in calls)
    assert calls[0][1] != calls[1][1] and calls[1][1] == candidate['content']
    assert all(call[2]['evaluation_example_id'] == example['id'] for call in calls)
    assert all(call[2]['evaluation_example_id'] != other['id'] for call in calls)
    listed = client.get('/api/v1/evaluations/runs', headers=admin).json['data']['items']
    assert next(r for r in listed if r['id'] == run['id'])['scope'] == 'single'
    complete = client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '全部题目', 'reviewed_only': False}).json['data']
    assert complete['scope'] == 'dataset' and complete['total'] == 2


def test_single_question_acceptance_never_publishes_even_for_one_question_set(app, client, admin, dataset, monkeypatch):
    did, example, _ = dataset
    _, candidate = save(client, admin)
    assert client.post(f"/api/v1/evaluations/examples/{example['id']}/review", headers=admin,
        json={'expected_revision': 1, 'confirmed': True}).status_code == 200
    run = client.post('/api/v1/evaluations/runs', headers=admin,
        json=single_request(dataset, overrides={'answer_robot': candidate['id']})).json['data']
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', lambda *args, **kwargs: {'answer': '99元', 'status': 'SUCCESS'})
    assert evaluation_worker.process_one(app)
    reviewed = client.post(f"/api/v1/evaluations/runs/{run['id']}/reviews/{example['id']}",
        headers=admin, json={'candidate': 1})
    assert reviewed.status_code == 200
    assert any('单题测试' in reason for reason in reviewed.json['data']['quality_reasons'])
    # Scope remains a gate even if the legacy reviewed_only flag is true.
    with app.app_context():
        row = db.session.get(EvaluationRun, UUID(run['id']))
        row.snapshot = {**row.snapshot, 'reviewed_only': True}
        db.session.commit()
    check = client.get('/api/v1/prompts/answer_robot/versions/2/release-check', headers=admin).json['data']
    assert not check['eligible'] and any('单题测试' in reason for reason in check['reasons'])
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin,
        json={'version': 2, 'expected_generation': 1, 'evaluation_run_id': run['id'], 'dataset_id': did}).status_code == 409
    formal = approved_run(app, client, admin, dataset, monkeypatch, candidate['id'])
    assert formal['scope'] == 'dataset'
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin,
        json={'version': 2, 'expected_generation': 1, 'evaluation_run_id': formal['id'], 'dataset_id': did}).status_code == 200


def test_single_question_rejects_invalid_stale_deleted_and_foreign_selection(client, admin, dataset):
    _, example, payload = dataset
    invalids = [{'example_id': None}, {'example_id': ''}, {'example_id': True}, {'example_id': []},
                {'expected_revision': None}, {'expected_revision': True}, {'expected_revision': 0},
                {'expected_revision': '1'}, {'expected_revision': 1.0}]
    for changes in invalids:
        response = client.post('/api/v1/evaluations/runs', headers=admin, json=single_request(dataset, **changes))
        assert response.status_code == 422, response.json
    for omitted in ('example_id', 'expected_revision'):
        request = single_request(dataset); request.pop(omitted)
        assert client.post('/api/v1/evaluations/runs', headers=admin, json=request).status_code == 422
    assert client.post('/api/v1/evaluations/runs', headers=admin,
        json=single_request(dataset, example_id=str(uuid4()))).status_code == 404
    options = client.get('/api/v1/evaluations/options', headers=admin).json['data']['knowledge_bases']
    other_base = next(row for row in options if not row['dataset_id'])
    other = client.post('/api/v1/evaluations/datasets', headers=admin,
        json={'name': '另一个库', 'knowledge_base_id': other_base['id']}).json['data']
    assert client.post('/api/v1/evaluations/runs', headers=admin,
        json=single_request(dataset, dataset_id=other['id'])).status_code == 404
    assert client.put(f"/api/v1/evaluations/examples/{example['id']}", headers=admin,
        json={**payload, 'expected_revision': 1}).status_code == 200
    response = client.post('/api/v1/evaluations/runs', headers=admin, json=single_request(dataset))
    assert response.status_code == 409 and '已修改' in response.json['message']
    assert client.delete(f"/api/v1/evaluations/examples/{example['id']}", headers=admin,
        json={'expected_revision': 2}).status_code == 200
    assert client.post('/api/v1/evaluations/runs', headers=admin,
        json=single_request(dataset, expected_revision=2)).status_code == 404
    assert client.get('/api/v1/evaluations/runs', headers=admin).json['data']['items'] == []


def test_single_question_prompt_coverage_uses_selected_question_only(client, admin, dataset):
    did, example, payload = dataset
    summary = client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
        json={**payload, 'name': '摘要题', 'inputs': {'task': 'summary', 'robot': False,
            'question': '压缩会话', 'context': {'turns': [{'question': '门票多少钱', 'answer': '99元'}]}}}).json['data']
    assert summary['prompt_keys'] == ['summarize']
    assert example['prompt_keys'] == ['answer_robot', 'review_answer']
    _, candidate = save(client, admin, key='summarize')
    response = client.post('/api/v1/evaluations/runs', headers=admin,
        json=single_request(dataset, overrides={'summarize': candidate['id']}))
    assert response.status_code == 422 and '未覆盖' in response.json['message']
    response = client.post('/api/v1/evaluations/runs', headers=admin,
        json=single_request((did, summary, payload), overrides={'summarize': candidate['id']}))
    assert response.status_code == 202
    detail = client.get(f"/api/v1/evaluations/runs/{response.json['data']['id']}", headers=admin).json['data']
    assert detail['snapshot']['covered_prompt_keys'] == ['summarize']
    assert detail['snapshot']['examples'][0]['id'] == summary['id']


def test_run_history_filters_before_limit_and_preserves_legacy_scope(app, client, admin, dataset):
    did, example, _ = dataset
    original = client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '旧评测集记录', 'reviewed_only': False}).json['data']
    bases = client.get('/api/v1/evaluations/options', headers=admin).json['data']['knowledge_bases']
    other_base = next(base for base in bases if not base['dataset_id'])
    other = client.post('/api/v1/evaluations/datasets', headers=admin,
        json={'name': '其他评测集', 'knowledge_base_id': other_base['id']}).json['data']
    with app.app_context():
        row = db.session.get(EvaluationRun, UUID(original['id']))
        snapshot = deepcopy(row.snapshot)
        snapshot.pop('scope')
        row.snapshot, row.status = snapshot, 'COMPLETED'
        arm = {'outputs': {}, 'scores': {}, 'error': None}
        row.results = [{'id': example['id'], 'baseline': arm, 'candidate': arm,
                        'review': {'candidate': 0, 'reviewed_by': str(row.created_by)}}]
        # Recent single runs and runs of other datasets must not hide this older run.
        for index in range(110):
            single = index < 55
            db.session.add(EvaluationRun(
                dataset_id=UUID(did if single else other['id']), name=f'新记录 {index}',
                status='COMPLETED', results=[],
                snapshot={**snapshot, 'scope': 'single' if single else 'dataset'},
                created_at=row.created_at + timedelta(seconds=index + 1),
            ))
        db.session.commit()
    endpoint = '/api/v1/evaluations/runs'
    items = client.get(endpoint, headers=admin, query_string={'dataset_id': did, 'scope': 'dataset'}).json['data']['items']
    assert [item['id'] for item in items] == [original['id']]
    assert items[0]['scope'] == 'dataset'
    assert items[0]['summary']['human_reviewed_count'] == 1
    assert items[0]['summary']['human']['candidate'] == 0
    assert items[0]['summary']['human_passed_count'] == 0
    assert items[0]['summary']['human_failed_count'] == 1
    assert 'results' not in items[0] and 'snapshot' not in items[0]
    singles = client.get(endpoint, headers=admin, query_string={'dataset_id': did, 'scope': 'single'}).json['data']['items']
    assert len(singles) == 50
    assert all(item['scope'] == 'single' and item['dataset_id'] == did for item in singles)
    assert singles[0]['name'] == '新记录 54'
    assert client.get(endpoint, headers=admin,
        query_string={'dataset_id': other['id'], 'scope': 'single'}).json['data']['items'] == []
    assert len(client.get(endpoint, headers=admin).json['data']['items']) == 50
    for invalid in ({'scope': ''}, {'scope': 'invalid'}, {'dataset_id': ''}, {'dataset_id': 'invalid'}):
        assert client.get(endpoint, headers=admin, query_string=invalid).status_code == 422


@pytest.mark.parametrize('scope', ['single', 'dataset'])
@pytest.mark.parametrize('robot', [True, False])
def test_evaluation_history_reaches_understanding_generation_and_review(app, client, admin, dataset, monkeypatch, scope, robot):
    from app.application.conversations import memory
    from app.application.qa import grounding_service, workflow
    from app.application.qa.retrieval_service import AnswerMaterial
    from app.integrations.ai.schemas import AnswerDraft, Review
    did, example, payload = dataset
    history = {'summary': '一家八口出游，想减少步行。', 'turns': [
        {'turn_no': 1, 'question': '我们共8个人，帮忙推荐游玩项目。', 'answer': '请问老人和小孩各有几位？'},
        {'turn_no': 2, 'question': '一个老人两个小孩。', 'answer': '可以选择步行较少的科普游。'},
    ]}
    question = '我们一共需要多少钱？'
    response = client.put(f"/api/v1/evaluations/examples/{example['id']}", headers=admin,
        json={**payload, 'status': 'enabled', 'expected_revision': 1,
              'inputs': {'question': question, 'robot': robot, 'context': history}})
    assert response.status_code == 200
    selected = response.json['data']
    request = {'dataset_id': did, 'name': '上下文链路验证'}
    if scope == 'single':
        request.update(example_id=selected['id'], expected_revision=selected['revision'])
    run = client.post('/api/v1/evaluations/runs', headers=admin, json=request).json['data']
    # Reproduce the actual trace: rewriting can omit the previously stated headcount.
    resolved = '一行人有老人和两个小孩，科普游按99元票价需要多少钱？'
    observed = {'understand': [], 'retrieve': [], 'generate': [], 'review': []}
    def understand(prompt, material, **kwargs):
        observed['understand'].append(deepcopy(material))
        assert material == {'question': question, 'history': history}
        return {'resolved_question': resolved, 'clarification': None}, 'test'
    def retrieve(base, query, **kwargs):
        observed['retrieve'].append(query)
        assert query == resolved
        source = {'source_id': 'S1', 'document_id': example['reference']['expected_document_ids'][0],
                  'document_title': '价格表', 'content': '科普游统一票价为99元/人。', 'modality': 'text'}
        return AnswerMaterial([source], [], {}, 1)
    def complete(prompt, material, *, schema, **kwargs):
        phase = 'generate' if schema is AnswerDraft else 'review'
        assert schema in (AnswerDraft, Review)
        observed[phase].append(deepcopy(material))
        assert material['question'] == {
            'current_question': question, 'resolved_question': resolved,
            'previous_user_questions': [turn['question'] for turn in history['turns']],
            'conversation_summary': history['summary'],
        }
        assert material['scope']['conversation_context'] == history
        assert material['scope']['resolved_question'] == resolved
        if schema is AnswerDraft:
            return {'answerable': True, 'blocks': [{'text': '按统一票价99元估算，8人共792元。', 'evidence_ids': ['S1.1']}]}, 'test'
        return {'complete': True, 'checks': [{'id': '1', 'supported': True}]}, 'test'
    monkeypatch.setattr(memory, 'complete_json', understand)
    monkeypatch.setattr(workflow, 'retrieve_for_answer', retrieve)
    monkeypatch.setattr(grounding_service, 'complete_json', complete)
    assert evaluation_worker.process_one(app)
    result = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    assert result['status'] == 'COMPLETED', result
    assert result['snapshot']['examples'][0]['inputs']['context'] == history
    assert all(len(calls) == 2 for calls in observed.values()), observed
    for arm in ('baseline', 'candidate'):
        assert '8人共792元' in result['results'][0][arm]['outputs']['answer']
        assert result['results'][0][arm]['outputs']['resolved_question'] == resolved
