import json

from test_knowledge_bases import login

from app.application.prompts.registry import NEW_KEYS, published_snapshot
from app.application.qa import planning, workflow
from app.application.robots.identity import identity_scope
from app.core.extensions import db
from app.entities import KnowledgeBase, PromptTemplate, PromptVersion


def test_database_contains_exactly_seven_published_v1(app, client):
    with app.app_context():
        snapshot = published_snapshot()
        assert set(snapshot) == NEW_KEYS
        assert all(v['version'] == 1 for v in snapshot.values())
        assert db.session.query(PromptTemplate).count() == 7
        assert db.session.query(PromptVersion).count() == 7
        assert 'direct_answer' in json.loads(snapshot['conversation_plan']['content'])['sections']['common']
        assert '机器人名称' in snapshot['robot_persona']['content']
    headers = login(client)
    assert len(client.get('/api/v1/prompts', headers=headers).json['data']['items']) == 7
    assert client.post('/api/v1/prompts/consolidation/prepare', headers=headers).status_code == 404


def test_current_robot_routes_once_with_device_identity(app, monkeypatch):
    calls = []
    def complete(prompt, material, **kwargs):
        calls.append(prompt)
        assert '"robot_name": "W1导览机器人"' in prompt
        return {'intent': 'chat', 'resolved_question': '你好', 'direct_answer': '你好，我是W1导览机器人。'}, 'test'
    monkeypatch.setattr(planning, 'complete_json', complete)
    with app.app_context(), identity_scope('W1导览机器人'):
        base_id = db.session.scalar(db.select(KnowledgeBase.id))
        result = workflow.answer_question('你好', base_id, {}, robot=True)
    assert result['answer'] == '你好，我是W1导览机器人。'
    assert len(calls) == 1
    assert result['execution_trace']['pipeline_version'] == 'conversation-v3'


def test_city_label_is_returned_in_robot_list_and_detail(client, monkeypatch):
    from app.application.realtime import service
    headers = login(client)
    base = client.get('/api/v1/robots/knowledge-base-options', headers=headers).json['data']['items'][0]['id']
    monkeypatch.setattr(service, '_get', lambda *a: {'location': [{'id': '101271101', 'adm1': '四川省', 'adm2': '宜宾市', 'name': '宜宾'}]})
    response = client.post('/api/v1/robots', headers=headers, json={'serial_no': 'new-city', 'knowledge_base_id': base,
                           'default_location': '101271101', 'timezone': 'Asia/Shanghai'})
    assert response.status_code == 201, response.json
    robot = response.json['data']
    assert '宜宾' in robot['default_location_name']
    detail = client.get('/api/v1/robots/' + robot['id'], headers=headers).json['data']
    assert detail['timezone'] == 'Asia/Shanghai'
    assert detail['default_location_name'] == robot['default_location_name']
