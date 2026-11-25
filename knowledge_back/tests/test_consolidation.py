from copy import deepcopy
from uuid import UUID

import pytest
from test_knowledge_bases import login
from test_prompt_evaluations import dataset as dataset_fixture
from test_realtime_tools import CLOCK, weather_fixture

from app.application.prompts.consolidation import prepare
from app.application.prompts.registry import NEW_KEYS, prompt_scope, published_snapshot
from app.application.qa import grounding_service, planning, workflow
from app.application.qa.retrieval_service import AnswerMaterial
from app.core.extensions import db
from app.entities import EvaluationRun, KnowledgeBase, PromptTemplate, PromptVersion
from app.integrations.ai.chat_adapter import ChatFormatError


@pytest.fixture
def admin(client):
    return login(client)


dataset = dataset_fixture


def test_prepare_preserves_published_edits_and_history(app, client, admin):
    with app.app_context():
        old = published_snapshot()
        version = db.session.get(PromptVersion, UUID(old["answer_robot"]["id"]))
        version.content += "\n用户专有表达约束。"
        db.session.commit()
        old = published_snapshot()
    response = client.post('/api/v1/prompts/consolidation/prepare', headers=admin)
    assert response.status_code == 200, response.json
    bundle = response.json['data']['candidate']
    assert set(bundle) == NEW_KEYS
    assert "用户专有表达约束" in bundle['answer_generate']['content']
    with app.app_context():
        assert published_snapshot() == old
    assert client.post('/api/v1/prompts/consolidation/prepare', headers=admin).json['data']['candidate'] == bundle


def test_migration_snapshot_freezes_both_protocols_and_refuses_draft_publication(app, client, admin, dataset):
    client.post('/api/v1/prompts/consolidation/prepare', headers=admin)
    response = client.post('/api/v1/evaluations/runs', headers=admin, json={"name": "迁移调试", "dataset_id": dataset[0], "reviewed_only": False, "migration": True})
    assert response.status_code == 202, response.json
    run_id = response.json['data']['id']
    with app.app_context():
        row = db.session.get(EvaluationRun, UUID(run_id))
        assert len(row.snapshot['baseline']) == 10 and len(row.snapshot['candidate']) == 7
        assert row.snapshot['examples'][0]['inputs']['realtime']['fixtures'] == []
    blocked = client.post('/api/v1/prompts/consolidation/publish', headers=admin, json={"evaluation_run_id": run_id})
    assert blocked.status_code == 409 and "草稿" in blocked.json['message']
    with app.app_context():
        assert len(published_snapshot()) == 10


def test_candidate_weather_uses_generation_and_independent_review(app, monkeypatch):
    with app.app_context():
        bundle = prepare(None)
        base = db.session.scalar(db.select(KnowledgeBase))
        base_id = base.id
        db.session.commit()
    monkeypatch.setattr(planning, 'complete_json', lambda *a, **k: ({"intent": "realtime", "resolved_question": "宜宾今天天气", "tool_requests": [{"name": "get_weather"}]}, "planner"))
    calls = []
    def complete(prompt, material, **kwargs):
        calls.append((kwargs['schema'].__name__, prompt))
        if kwargs['schema'].__name__ == 'AnswerDraft':
            assert '18' in str(material['sources'])
            return {"answerable": True, "blocks": [{"text": "宜宾11月12日当前晴，18摄氏度。", "evidence_ids": ["tool-1.1"]}]}, 'model'
        return {"checks": [{"id": "1", "supported": True}], "complete": True}, 'reviewer'
    monkeypatch.setattr(grounding_service, 'complete_json', complete)
    monkeypatch.setattr(workflow, 'retrieve_for_answer', lambda *a, **k: pytest.fail('pure realtime cannot retrieve'))
    with app.app_context(), prompt_scope(bundle):
        result = workflow.answer_question('今天天气怎么样', base_id, {}, robot=True, runtime=CLOCK, fixtures=[weather_fixture()])
    assert result['answer'] == '宜宾11月12日当前晴，18摄氏度。'
    assert result['answer_kind'] == 'realtime' and result['sources'] == []
    assert [c[0] for c in calls] == ['AnswerDraft', 'Review']
    assert '小维' in calls[0][1]
    assert result['execution_trace']['tools'][0]['source'] == 'fixture-qweather'
    assert set(result['execution_trace']['used_prompt_keys']) == {'conversation_plan', 'answer_generate', 'review_answer', 'robot_persona'}
    assert {r['key'] for r in result['execution_trace']['prompt_compositions']} == {'conversation_plan', 'answer_generate', 'review_answer'}


def test_mixed_failure_keeps_business_answer(app, monkeypatch):
    with app.app_context():
        bundle = prepare(None)
        base_id = db.session.scalar(db.select(KnowledgeBase.id))
        db.session.commit()
    monkeypatch.setattr(planning, 'complete_json', lambda *a, **k: ({'intent': 'realtime', 'resolved_question': '天气和雨天规则', 'knowledge_query': '雨天游玩规定', 'unavailable': ['unsupported']}, 'model'))
    monkeypatch.setattr(workflow, 'retrieve_for_answer', lambda *a, **k: AnswerMaterial([{'source_id': '1', 'chunk_id': '1', 'document_id': '1', 'document_title': '规则', 'content': '雨天注意防滑。'}], [], {}, 1))
    monkeypatch.setattr(workflow, 'generate_answer', lambda *a, **k: ('雨天注意防滑。', [], 'model', 'SUCCESS'))
    with app.app_context(), prompt_scope(bundle):
        result = workflow.answer_question('现在下雨吗，雨天怎么玩', base_id, {}, robot=True, runtime=CLOCK, fixtures=[])
    assert '雨天注意防滑' in result['answer'] and '暂不支持' in result['answer']
    assert result['status'] == 'PARTIAL'


def test_web_plan_cannot_request_tools(app, monkeypatch):
    with app.app_context():
        bundle = prepare(None)
        base_id = db.session.scalar(db.select(KnowledgeBase.id))
        db.session.commit()
    monkeypatch.setattr(planning, 'complete_json', lambda *a, **k: ({'intent': 'realtime', 'resolved_question': '天气', 'tool_requests': [{'name': 'get_weather'}]}, 'model'))
    with app.app_context(), prompt_scope(bundle), pytest.raises(ChatFormatError):
        planning.plan('明天呢', {'turns': [{'question': '今天天气'}]}, base_id, robot=False, runtime=CLOCK)


def test_archived_versions_stay_readable_and_snapshot_is_seven(app, client, admin):
    with app.app_context():
        old = deepcopy(published_snapshot())
        bundle = prepare(None)
        for row in db.session.scalars(db.select(PromptTemplate)):
            row.archived = row.key not in NEW_KEYS
            if row.key in bundle:
                row.active_version = bundle[row.key]['version']
        db.session.commit()
        assert set(published_snapshot()) == NEW_KEYS
        with prompt_scope(old):
            from app.application.prompts.registry import get_prompt
            assert get_prompt('answer_web') == old['answer_web']['content']
    assert len(client.get('/api/v1/prompts', headers=admin).json['data']['items']) == 7
    assert len(client.get('/api/v1/prompts?include_archived=1', headers=admin).json['data']['items']) == 12
    assert client.get('/api/v1/prompts/answer_web', headers=admin).status_code == 200
    assert client.post('/api/v1/prompts/answer_web/versions', headers=admin, json={'content': '无权修改历史用途'*10}).status_code == 409


def test_migration_publish_is_atomic_and_old_snapshot_remains_executable(app, client, admin, dataset):
    from app.entities import EvaluationExample, now
    did, example, _ = dataset
    client.post('/api/v1/prompts/consolidation/prepare', headers=admin)
    cases = [(False, 'knowledge'), (True, 'knowledge'), (True, 'chat'), (True, 'general'),
             (True, 'clarification'), (True, 'realtime'), (True, 'realtime'), (True, 'realtime')]
    with app.app_context():
        original = db.session.get(EvaluationExample, UUID(example['id']))
        user_id = original.created_by
        original.reviewed_by, original.reviewed_at = user_id, now()
        for i, (robot, kind) in enumerate(cases):
            db.session.add(EvaluationExample(dataset_id=UUID(did), name=f'迁移场景{i}',
                inputs={'question': '测试问题', 'robot': robot, 'context': {'turns': [{'question': '历史条件', 'answer': '历史回答'}]}},
                reference={'expected_answer_kind': kind}, reviewed_by=user_id, reviewed_at=now()))
        db.session.commit()
    response = client.post('/api/v1/evaluations/runs', headers=admin, json={'name': '迁移验收', 'dataset_id': did, 'migration': True})
    assert response.status_code == 202, response.json
    run_id = response.json['data']['id']
    with app.app_context():
        row = db.session.get(EvaluationRun, UUID(run_id))
        old = deepcopy(row.snapshot['baseline'])
        results = []
        for e in row.snapshot['examples']:
            robot = e['inputs'].get('robot', False)
            kind = e['reference'].get('expected_answer_kind') or 'knowledge'
            compositions = [{'key': key, 'sections': ['common', 'robot' if robot else 'web', 'knowledge', 'realtime'],
                             'channel': 'robot' if robot else 'web',
                             'evidence': ['knowledge', 'realtime'] if kind == 'realtime' else ['knowledge']}
                            for key in ('conversation_plan', 'answer_generate', 'review_answer')]
            output = {'answer_kind': kind, 'used_prompt_keys': list(NEW_KEYS), 'prompt_compositions': compositions,
                      'tools': [{'status': 'error', 'reason': 'missing_location'}] if kind == 'realtime' else []}
            results.append({'id': e['id'], 'baseline': {'outputs': {}, 'error': None},
                            'candidate': {'outputs': output, 'error': None}, 'review': {'candidate': 1, 'reviewed_by': str(user_id)}})
        row.status, row.results = 'COMPLETED', results
        db.session.commit()
    published = client.post('/api/v1/prompts/consolidation/publish', headers=admin, json={'evaluation_run_id': run_id})
    assert published.status_code == 200, published.json
    with app.app_context():
        assert set(published_snapshot()) == NEW_KEYS
        with prompt_scope(old):
            from app.application.prompts.registry import get_prompt
            assert get_prompt('robot_interaction') == old['robot_interaction']['content']
    assert client.post('/api/v1/prompts/consolidation/publish', headers=admin, json={'evaluation_run_id': run_id}).status_code == 409
