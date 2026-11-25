from uuid import UUID, uuid4

import pytest
from test_page_authorization import grant
from test_page_authorization import reader as reader_fixture
from test_prompt_evaluations import admin as admin_fixture
from test_prompt_evaluations import dataset as dataset_fixture

from app.core.extensions import db
from app.entities import EvaluationDataset, KnowledgeBase, QAConversation, QALog, Robot, User, now

admin = admin_fixture
dataset = dataset_fixture
reader = reader_fixture


@pytest.fixture
def logs(app, dataset):
    with app.app_context():
        base = db.session.get(EvaluationDataset, UUID(dataset[0])).knowledge_base_id
        other = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.code == 'general')).id
        user = db.session.scalar(db.select(User).where(User.username == 'admin'))
        robot = Robot(serial_no='history-import', name='测试机器人', knowledge_base_id=base)
        db.session.add(robot); db.session.flush()
        rows = {}
        for name in ['web', 'other', 'deleted', 'robot']:
            row = QAConversation(source_type='ROBOT' if name == 'robot' else 'WEB',
                user_id=None if name == 'robot' else user.id, robot_id=robot.id if name == 'robot' else None,
                knowledge_base_id=other if name == 'other' else base,
                title=name + ' 测试历史', creation_request_id=str(uuid4()), next_turn_no=10,
                deleted_at=now() if name == 'deleted' else None,
                closed_at=now() if name == 'robot' else None,
                memory_summary='包含未来问题答案的摘要，不允许导入', summary_through_turn_no=9)
            db.session.add(row); db.session.flush()
            for n, status in enumerate(['SUCCESS', 'PARTIAL', 'FAILED', 'NO_EVIDENCE', 'PENDING', 'CANCELLED', 'SOURCES_ONLY', 'SUCCESS', 'SUCCESS'], 1):
                db.session.add(QALog(request_id=str(uuid4()), source_type=row.source_type,
                    user_id=row.user_id, robot_id=row.robot_id, knowledge_base_id=row.knowledge_base_id,
                    conversation_id=row.id, turn_no=n, question=f'原问题 {n}',
                    answer=f'原回答 {n}' if n != 9 else '', status=status,
                    answer_kind='clarification' if n == 8 else 'knowledge'))
            rows[name] = str(row.id)
        db.session.commit()
        return {**rows, 'owner': str(user.id), 'robot_owner': str(robot.id), 'base': base,
                'prefix': f'/api/v1/evaluations/datasets/{dataset[0]}/history'}


def test_history_scope_pagination_and_closed_robot_session(client, admin, logs):
    prefix = logs['prefix']
    owners = client.get(prefix + '/owners?source_type=WEB', headers=admin).json['data']
    assert owners['total'] == 1 and owners['items'][0]['conversation_count'] == 1
    assert client.get(prefix + '/owners?source_type=WEB&q=does-not-exist', headers=admin).json['data']['items'] == []
    sessions = client.get(prefix + f'/conversations?source_type=WEB&owner_id={logs["owner"]}', headers=admin).json['data']
    assert [row['id'] for row in sessions['items']] == [logs['web']]
    assert client.get(prefix + f'/conversations?source_type=WEB&owner_id={logs["owner"]}&q=原问题', headers=admin).json['data']['total'] == 1
    endpoint = prefix + f'/conversations/{logs["web"]}/turns'
    first = client.get(endpoint + '?source_type=WEB&page_size=2', headers=admin).json['data']
    second = client.get(endpoint + '?source_type=WEB&page_size=2&page=2', headers=admin).json['data']
    assert [row['turn_no'] for row in first['items']] == [1, 2]
    assert [row['turn_no'] for row in second['items']] == [3, 4]
    assert not second['items'][0]['importable'] and second['items'][1]['importable']
    assert first['total'] == 9 and 'memory_summary' not in first['conversation']
    robot = client.get(prefix + f'/conversations/{logs["robot"]}/context?source_type=ROBOT&start=7&end=8&task=summary', headers=admin)
    assert robot.status_code == 200
    assert [row['answer_kind'] for row in robot.json['data']['context']['turns']] == ['knowledge', 'clarification']


def test_import_is_ordered_excludes_unfinished_and_freezes_independently(app, client, admin, dataset, logs):
    prefix = logs['prefix'] + f'/conversations/{logs["web"]}/context'
    copied = client.get(prefix + '?source_type=WEB&start=1&end=6&task=answer', headers=admin).json['data']
    assert copied['skipped_count'] == 3
    assert copied['context']['summary'] == ''
    assert [turn['turn_no'] for turn in copied['context']['turns']] == [1, 2, 4]
    assert all(t['source_conversation_id'] == logs['web'] and t['source_log_id'] for t in copied['context']['turns'])
    did, example, payload = dataset
    result = client.put(f'/api/v1/evaluations/examples/{example["id"]}', headers=admin,
        json={**payload, 'inputs': {'question': '这些包括什么？', 'context': copied['context']},
              'expected_revision': 1, 'status': 'enabled'})
    assert result.status_code == 200, result.json
    with app.app_context():
        row = db.session.get(QAConversation, UUID(logs['web'])); row.deleted_at = now()
        log = db.session.scalar(db.select(QALog).where(QALog.conversation_id == row.id, QALog.turn_no == 1))
        log.answer = '原会话后续变化'; db.session.commit()
    saved = client.get(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin).json['data']['items'][0]
    assert saved['inputs']['context'] == copied['context']
    assert saved['reference']['answer_points'] == payload['reference']['answer_points']
    assert saved['status'] == 'enabled' and saved['revision'] == 2


def test_history_requires_both_permissions_on_every_endpoint(app, client, admin, dataset, logs, reader):
    paths = [logs['prefix'] + '/owners?source_type=WEB',
             logs['prefix'] + f'/conversations?source_type=WEB&owner_id={logs["owner"]}',
             logs['prefix'] + f'/conversations/{logs["web"]}/turns?source_type=WEB',
             logs['prefix'] + f'/conversations/{logs["web"]}/context?source_type=WEB&start=1&end=2&task=answer']
    for path in paths:
        assert client.get(path, headers=reader).status_code == 403
    grant(app, '/evaluations')
    for path in paths:
        assert client.get(path, headers=reader).status_code == 403
    grant(app, '/qa-logs')
    for path in paths:
        assert client.get(path, headers=reader).status_code == 200


def test_history_rejects_foreign_deleted_wrong_channel_and_disabled_base(app, client, admin, logs):
    for name, source in [('other', 'WEB'), ('deleted', 'WEB'), ('robot', 'WEB')]:
        for suffix in ['turns', 'context']:
            response = client.get(logs['prefix'] + f'/conversations/{logs[name]}/{suffix}?source_type={source}&start=1&end=2&task=answer', headers=admin)
            assert response.status_code == 404
    with app.app_context():
        base = db.session.get(KnowledgeBase, logs['base']); base.status = 'disabled'; db.session.commit()
    assert client.get(logs['prefix'] + '/owners?source_type=WEB', headers=admin).status_code == 409


@pytest.mark.parametrize('query', ['start=0&end=2', 'start=3&end=2', 'start=1&end=10', 'start=x&end=2', 'end=2', 'start=3&end=3', 'start=9&end=9'])
def test_history_invalid_or_empty_ranges(client, admin, logs, query):
    response = client.get(logs['prefix'] + f'/conversations/{logs["web"]}/context?source_type=WEB&task=answer&{query}', headers=admin)
    assert response.status_code == 422


def test_import_bounds_do_not_silently_truncate_answers(app, client, admin, logs):
    endpoint = logs['prefix'] + f'/conversations/{logs["web"]}/context?source_type=WEB'
    with app.app_context():
        row = db.session.get(QAConversation, UUID(logs['web'])); row.next_turn_no = 40
        log = db.session.scalar(db.select(QALog).where(QALog.conversation_id == row.id, QALog.turn_no == 1))
        log.answer = '中' * 7000; db.session.commit()
    assert client.get(endpoint + '&start=1&end=31&task=answer', headers=admin).status_code == 422
    assert client.get(endpoint + '&start=1&end=1&task=summary', headers=admin).status_code == 422
    assert client.get(endpoint + '&start=1&end=1&task=answer', headers=admin).json['data']['context']['turns'][0]['answer'] == '中' * 7000
