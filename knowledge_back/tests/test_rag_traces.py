from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from test_conversations import first
from test_knowledge_bases import login

from app.application.qa import trace_details
from app.entities import QALog
from app.extensions import db
from app.workers import qa_worker

pytest_plugins = ["test_conversations"]


def endpoint(item):
    return f"/api/v1/admin/qa-conversations/{item['conversation_id']}/turns/{item['turn_id']}/trace"


def test_trace_permissions_parent_binding_and_old_logs(app, client, setup):
    item = first(client, setup)
    assert client.get(endpoint(item)).status_code == 401
    runner = app.test_cli_runner()
    assert runner.invoke(args=['create-user', '--username', 'trace-reader'],
                         input='Reader-Password-2026!\nReader-Password-2026!\n').exit_code == 0
    reader = login(client, 'trace-reader', 'Reader-Password-2026!')
    assert client.get(endpoint(item), headers=reader).status_code == 403
    result = client.get(endpoint(item), headers=setup['headers'])
    assert result.status_code == 200
    assert result.json['data']['runs'] == []
    assert '未保存流程' in result.json['data']['message']
    other = first(client, setup, key='another')
    wrong = {**item, 'conversation_id': other['conversation_id']}
    assert client.get(endpoint(wrong), headers=setup['headers']).status_code == 404


def run_record(run_id, order, *, name='rag.turn', error=None, end=True):
    start = datetime.now(UTC)
    return SimpleNamespace(id=run_id, dotted_order=order, name=name, run_type='chain',
        start_time=start, end_time=start + timedelta(seconds=1) if end else None,
        error=error, inputs={'question': '测试', 'api_key': 'never-return',
            'url': 'https://objects.test/file?X-Amz-Signature=private'},
        outputs={'answer': '答案'}, prompt_tokens=30, completion_tokens=10, total_tokens=40)


def test_remote_tree_is_scoped_to_saved_root_and_scrubbed(app, client, setup, monkeypatch):
    item = first(client, setup)
    root_id, child_id = str(uuid4()), str(uuid4())
    root_order = '20261112T000000Z' + root_id
    root = run_record(root_id, root_order)
    child = run_record(child_id, root_order + '.20261112T000001Z' + child_id, name='understand')
    unrelated = run_record(str(uuid4()), 'unrelated', name='other user')
    def read(config, client, local, limit):
        assert local['run_id'] == root_id and limit == 200
        return [child, unrelated, root]
    monkeypatch.setattr(trace_details, 'read_run_tree', read)
    app.extensions['langsmith'] = object()
    with app.app_context():
        log = db.session.get(QALog, UUID(item['turn_id']))
        log.execution_trace = {'run_id': root_id, 'content_captured': True}
        db.session.commit()
    result = client.get(endpoint(item), headers=setup['headers']).json['data']
    assert result['source'] == 'langsmith'
    assert [r['id'] for r in result['runs']] == [root_id, child_id]
    assert result['runs'][1]['parent_id'] == root_id
    assert result['runs'][0]['latency_ms'] == 1000
    assert 'never-return' not in str(result) and 'private' not in str(result)
    assert result['runs'][0]['inputs']['question'] == '测试'
    # Remote detail does not ride on ordinary user/robot history responses.
    personal = client.get(f"/api/v1/web/conversations/{item['conversation_id']}/turns", headers=setup['headers'])
    assert 'execution_trace' not in personal.json['data']['items'][0]


def test_failed_worker_preserves_local_tree_and_remote_errors_fall_back(app, client, setup, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('provider private diagnostics')
    monkeypatch.setattr(qa_worker, 'answer_question', fail)
    item = first(client, setup)
    assert qa_worker.process_one(app)
    result = client.get(endpoint(item), headers=setup['headers']).json['data']
    assert result['source'] == 'local' and result['status'] == 'FAILED'
    assert result['local']['steps'][0]['status'] == 'failed'
    assert any(s['name'] == 'prepare_memory' for s in result['local']['steps'])
    assert 'provider private' not in str(result)
    def unavailable(*args):
        raise RuntimeError('secret transport error')
    app.extensions['langsmith'] = object()
    monkeypatch.setattr(trace_details, 'read_run_tree', unavailable)
    result = client.get(endpoint(item), headers=setup['headers']).json['data']
    assert result['local']['run_id'] and result['source'] == 'local'
    assert 'secret transport' not in str(result)


def test_soft_deleted_conversation_retains_admin_trace(app, client, setup):
    item = first(client, setup)
    assert qa_worker.process_one(app)
    client.delete(f"/api/v1/web/conversations/{item['conversation_id']}", headers=setup['headers'])
    result = client.get(endpoint(item), headers=setup['headers'])
    assert result.status_code == 200 and result.json['data']['local']['steps']


def test_trace_payload_is_bounded_and_never_contains_credentials():
    value = trace_details.safe_data({'Authorization': 'Bearer confidential',
        'text': 'lsv2_pt_' + 'x' * 40, 'big': 'x' * 20000, 'list': list(range(200))})
    assert value['Authorization'] == '[已隐藏]' and 'lsv2_' not in value['text']
    assert len(value['big']) < 17000 and len(value['list']) == 101
