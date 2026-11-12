from copy import deepcopy
from uuid import UUID

import pytest
from test_knowledge_bases import login

from app.application.evaluations.service import aggregate
from app.application.prompts.registry import get_prompt, prompt_scope, published_snapshot
from app.core.extensions import db
from app.entities import Document, DocumentVersion, EvaluationRun, KnowledgeBase, PromptVersion
from app.workers import evaluation_worker


@pytest.fixture
def admin(client):
    return login(client)


def save(client, admin, key='answer_robot'):
    before = client.get(f'/api/v1/prompts/{key}', headers=admin).json['data']
    content = before['versions'][0]['content'] + '\n测试改进：保留必要条件，优先直接回答。'
    response = client.post(f'/api/v1/prompts/{key}/versions', headers=admin, json={'content': content, 'note': '测试版本'})
    assert response.status_code == 201, response.json
    return before, response.json['data']


def test_draft_isolated_publication_cas_and_running_snapshot(app, client, admin, dataset, monkeypatch):
    with app.app_context():
        initial = published_snapshot()
    before, new = save(client, admin)
    with app.app_context():
        assert published_snapshot() == initial
    endpoint = '/api/v1/prompts/answer_robot/publish'
    assert client.post(endpoint, headers=admin, json={'version': new['version'], 'expected_generation': 1}).status_code == 409
    run = approved_run(app, client, admin, dataset, monkeypatch, new['id'])
    assert client.post(endpoint, headers=admin, json={'version': new['version'], 'expected_generation': 1, 'evaluation_run_id': run['id']}).status_code == 200
    assert client.post(endpoint, headers=admin, json={'version': 1, 'expected_generation': 1}).status_code == 409
    with app.app_context():
        assert get_prompt('answer_robot') == new['content']
        with prompt_scope(initial):
            assert get_prompt('answer_robot') == initial['answer_robot']['content']
        assert get_prompt('answer_robot') == new['content']
        old = db.session.get(PromptVersion, UUID(before['versions'][0]['id']))
        assert old.content == initial['answer_robot']['content']
    assert client.post(endpoint, headers=admin, json={'version': 1, 'expected_generation': 2}).status_code == 409
    rollback = approved_run(app, client, admin, dataset, monkeypatch, before['versions'][0]['id'])
    assert client.post(endpoint, headers=admin, json={'version': 1, 'expected_generation': 2, 'evaluation_run_id': rollback['id']}).status_code == 200


def test_prompt_and_evaluation_admin_permissions(app, client, admin):
    result = app.test_cli_runner().invoke(args=['create-user','--username','reader'], input='Reader-Password-2026!\nReader-Password-2026!\n')
    assert result.exit_code == 0
    reader = login(client, 'reader', 'Reader-Password-2026!')
    for path in ['/prompts', '/prompts/answer_web', '/evaluations/datasets', '/evaluations/runs', '/evaluations/options']:
        assert client.get('/api/v1' + path, headers=reader).status_code == 403
    assert client.post('/api/v1/prompts/answer_robot/versions', headers=admin, json=[]).status_code == 422
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin, json={'version': 999, 'expected_generation': 1}).status_code == 404


@pytest.fixture
def dataset(app, client, admin):
    with app.app_context():
        base = KnowledgeBase(code='evaluation-test', name='评测资料')
        db.session.add(base); db.session.flush()
        doc = Document(title='价格表', knowledge_base_id=base.id)
        db.session.add(doc); db.session.flush()
        version = DocumentVersion(document_id=doc.id, version_no=1, minio_bucket='test', minio_object_key='price', filename='price.txt', file_size=10, status='INDEXED', chunk_count=1, index_config_hash='config-v1')
        db.session.add(version); db.session.flush(); doc.current_version_id=version.id; db.session.commit()
        base_id, document_id = str(base.id), str(doc.id)
    row = client.post('/api/v1/evaluations/datasets', headers=admin, json={'name':'价格测试','knowledge_base_id':base_id}).json['data']
    payload = {'name':'票价','inputs':{'question':'票价是多少？','robot':True},'reference':{'expected_document_ids':[document_id],'answer_points':['99元'],'expected_status':'SUCCESS','source_notes':'价格表第一行'}}
    example = client.post(f"/api/v1/evaluations/datasets/{row['id']}/examples",headers=admin,json=payload).json['data']
    return row['id'], example, payload


def test_review_is_explicit_and_edit_invalidates_review(client, admin, dataset):
    did, example, payload = dataset
    endpoint=f"/api/v1/evaluations/examples/{example['id']}"
    assert example['reviewed_by'] is None
    assert client.post(endpoint+'/review',headers=admin,json={'expected_revision':1}).status_code==422
    assert client.post(endpoint+'/review',headers=admin,json={'expected_revision':1,'confirmed':True}).json['data']['reviewed_by']
    changed=client.put(endpoint,headers=admin,json={**payload,'expected_revision':1}).json['data']
    assert changed['reviewed_by'] is None and changed['revision']==2
    assert client.post(endpoint+'/review',headers=admin,json={'expected_revision':1,'confirmed':True}).status_code==409
    assert client.post('/api/v1/evaluations/runs',headers=admin,json={'dataset_id':did,'name':'不可伪造金标'}).status_code==422


def test_pair_freezes_drafts_labels_and_survives_example_deletion(app, client, admin, dataset, monkeypatch):
    did, example, _ = dataset
    _, candidate = save(client,admin)
    run = client.post('/api/v1/evaluations/runs',headers=admin,json={'dataset_id':did,'name':'草稿对比','reviewed_only':False,'overrides':{'answer_robot':candidate['id']}}).json['data']
    assert run['status']=='PENDING' and not run['reviewed_only']
    assert client.delete(f"/api/v1/evaluations/examples/{example['id']}",headers=admin,json={'expected_revision':1}).status_code==200
    seen=[]
    def evaluate(inputs, **kwargs):
        seen.append(get_prompt('answer_robot'))
        return {'answer':'票价99元','status':'SUCCESS','retrieved_documents':['价格表'],'cited_documents':['价格表']}
    monkeypatch.setattr(evaluation_worker,'evaluate_input',evaluate)
    assert evaluation_worker.process_one(app)
    detail=client.get(f"/api/v1/evaluations/runs/{run['id']}",headers=admin).json['data']
    assert detail['status']=='COMPLETED' and detail['summary']['paired_count']==1
    assert seen[0]!=seen[1] and seen[1]==candidate['content']
    assert detail['snapshot']['examples'][0]['reference']['answer_points']==['99元']
    assert detail['summary']['human_reviewed_count']==0
    result=client.post(f"/api/v1/evaluations/runs/{run['id']}/reviews/{example['id']}",headers=admin,json={'baseline':0,'candidate':1,'note':'候选保留了价格和条件'})
    assert result.json['data']['summary']['human']=={'baseline':0,'candidate':1}
    # A new-style review preserves the old baseline judgment without requiring it again.
    updated = client.post(f"/api/v1/evaluations/runs/{run['id']}/reviews/{example['id']}",
        headers=admin, json={'candidate': 0})
    assert updated.status_code == 200
    assert updated.json['data']['summary']['human'] == {'baseline': 0, 'candidate': 0}
    assert updated.json['data']['results'][0]['review']['note'] == ''


def test_index_change_stops_comparison_and_lease_is_fenced(app, client, admin, dataset, monkeypatch):
    did, _, _=dataset
    run=client.post('/api/v1/evaluations/runs',headers=admin,json={'dataset_id':did,'name':'索引变化','reviewed_only':False}).json['data']
    with app.app_context():
        version=db.session.scalar(db.select(DocumentVersion).where(DocumentVersion.minio_object_key=='price'))
        version.index_config_hash='config-v2'; db.session.commit()
    monkeypatch.setattr(evaluation_worker,'evaluate_input',lambda _, **kwargs:pytest.fail('must not execute after index change'))
    assert evaluation_worker.process_one(app)
    result=client.get(f"/api/v1/evaluations/runs/{run['id']}",headers=admin).json['data']
    assert result['status']=='FAILED' and '索引' in result['error_message'] and not result['results']
    with app.app_context():
        assert not evaluation_worker.update(UUID(run['id']),UUID(run['id']),results=[{'invalid':True}])
        assert not db.session.get(EvaluationRun,UUID(run['id'])).results


def test_pair_denominators_do_not_silently_score_failed_calls():
    good={'scores':{'status_accuracy':1},'error':None}
    bad={'scores':{},'error':'Timeout'}
    result=aggregate([{'baseline':good,'candidate':bad},{'baseline':good,'candidate':deepcopy(good)}])
    assert result['paired_count']==1
    assert result['baseline']['metrics']['status_accuracy']['count']==2
    assert result['candidate']['metrics']['status_accuracy']['count']==1
    assert result['candidate']['failures']==1 and result['delta']['status_accuracy']==0


def test_summary_and_suggestions_use_the_selected_prompt_versions(app, monkeypatch):
    from types import SimpleNamespace

    from app.application.conversations import memory
    from app.application.qa import evaluation, grounding_service
    from app.application.qa.evaluation import evaluate_input
    with app.app_context():
        base = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.code == 'general'))
        prompts = published_snapshot()
        prompts['summarize']['content'] = '摘要候选版本'
        seen = []
        def complete(instruction, material, **kwargs):
            seen.append((instruction, material))
            return {'summary':'用户计划带孩子游玩石海'}, 'fake'
        monkeypatch.setattr(memory, 'complete_json', complete)
        with prompt_scope(prompts):
            result = evaluate_input({'question':'压缩历史','knowledge_base_code':base.code,'task':'summary',
                'context':{'turns':[{'question':'我带孩子出游'}]}})
        assert result['answer'] == '用户计划带孩子游玩石海'
        assert seen[0][0] == '摘要候选版本'
        monkeypatch.setattr(evaluation, 'retrieve_for_answer', lambda *args: SimpleNamespace(context=[{'document_title':'票价表','document_id':'price-id'}]))
        monkeypatch.setattr(grounding_service, 'generate_suggestions', lambda sources: [{'question':'科普游套票多少钱？','source':{'document_title':'票价表','document_id':'price-id'}}])
        result = evaluate_input({'question':'套票','knowledge_base_code':base.code,'task':'suggestions'})
        assert result['answer'] == '科普游套票多少钱？' and result['cited_documents'] == ['票价表']


def test_experiment_cannot_claim_to_test_a_prompt_that_samples_never_use(client, admin, dataset):
    did, _, _ = dataset
    _, candidate = save(client, admin, key='summarize')
    response = client.post('/api/v1/evaluations/runs',headers=admin,json={'dataset_id':did,'name':'错误覆盖','reviewed_only':False,'overrides':{'summarize':candidate['id']}})
    assert response.status_code == 422 and '未覆盖' in response.json['message']


def approved_run(app, client, admin, dataset, monkeypatch, candidate_id):
    did, example, _ = dataset
    response = client.post(f"/api/v1/evaluations/examples/{example['id']}/review", headers=admin,
                           json={'expected_revision': example['revision'], 'confirmed': True})
    assert response.status_code == 200
    response = client.post('/api/v1/evaluations/runs', headers=admin, json={
        'dataset_id': did, 'name': '发布验收', 'overrides': {'answer_robot': candidate_id}})
    assert response.status_code == 202, response.json
    run = response.json['data']
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', lambda inputs, **kwargs: {
        'answer': '票价99元', 'status': 'SUCCESS',
        'retrieved_document_ids': example['reference']['expected_document_ids'],
        'cited_document_ids': example['reference']['expected_document_ids']})
    assert evaluation_worker.process_one(app)
    response = client.post(f"/api/v1/evaluations/runs/{run['id']}/reviews/{example['id']}",
        headers=admin, json={'candidate': 1})
    assert response.status_code == 200, response.json
    return response.json['data']


@pytest.mark.parametrize('failure', ['draft', 'unreviewed_label', 'pending', 'missing_pair',
    'error', 'unreviewed_answer', 'rejected_answer', 'other_version', 'other_prompt',
    'baseline_changed', 'environment', 'edited_example', 'not_covered'])
def test_release_cannot_bypass_quality_gate(app, client, admin, dataset, monkeypatch, failure):
    from app.entities import EvaluationExample
    _, candidate = save(client, admin)
    run = approved_run(app, client, admin, dataset, monkeypatch, candidate['id'])
    check = '/api/v1/prompts/answer_robot/versions/2/release-check'
    assert client.get(check, headers=admin).json['data']['eligible']
    with app.app_context():
        row = db.session.get(EvaluationRun, UUID(run['id']))
        snapshot, results = deepcopy(row.snapshot), deepcopy(row.results)
        if failure == 'draft': snapshot['reviewed_only'] = False
        if failure == 'unreviewed_label': snapshot['examples'][0]['reviewed_by'] = None
        if failure == 'pending': row.status = 'RUNNING'
        if failure == 'missing_pair': results = []
        if failure == 'error': results[0]['candidate']['error'] = 'Timeout'
        if failure == 'unreviewed_answer': results[0]['review'] = None
        if failure == 'rejected_answer': results[0]['review']['candidate'] = 0
        if failure == 'other_version': snapshot['candidate']['answer_robot'] = snapshot['baseline']['answer_robot']
        if failure == 'other_prompt': snapshot['candidate']['answer_web']['content'] += 'changed'
        if failure == 'baseline_changed': snapshot['baseline']['answer_robot']['content'] += 'old'
        if failure == 'environment': snapshot['environment_hash'] = 'outdated'
        if failure == 'edited_example':
            example = db.session.get(EvaluationExample, UUID(dataset[1]['id']))
            example.revision += 1
        if failure == 'not_covered': snapshot['covered_prompt_keys'] = []
        row.snapshot, row.results = snapshot, results
        db.session.commit()
    assert not client.get(check, headers=admin).json['data']['eligible']
    response = client.post('/api/v1/prompts/answer_robot/publish', headers=admin,
        json={'version': 2, 'expected_generation': 1, 'evaluation_run_id': run['id']})
    assert response.status_code == 409, response.json
    assert client.get('/api/v1/prompts/answer_robot', headers=admin).json['data']['active_version'] == 1


def test_document_picker_and_reference_validation(app, client, admin, dataset):
    from uuid import uuid4
    did, example, payload = dataset
    endpoint = f'/api/v1/evaluations/datasets/{did}/documents'
    items = client.get(endpoint, headers=admin).json['data']['items']
    assert [r['id'] for r in items] == example['reference']['expected_document_ids']
    assert items[0]['title'] == '价格表'
    assert client.get(endpoint + '?q=不存在', headers=admin).json['data']['items'] == []
    assert client.get(endpoint + '?q=不存在&selected=' + items[0]['id'], headers=admin).json['data']['items'] == items
    with app.app_context():
        base = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.code == 'general'))
        other = Document(title='其他库文档', knowledge_base_id=base.id)
        db.session.add(other); db.session.commit()
        other_id = str(other.id)
    for ids in [[other_id], [str(uuid4())], ['invalid']]:
        response = client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
            json={**payload, 'name': '无效文档', 'reference': {'expected_document_ids': ids}})
        assert response.status_code == 422
    assert client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
        json={**payload, 'name': '手写标题', 'reference': {'expected_documents': ['价格表']}}).status_code == 422
    with app.app_context():
        doc = db.session.get(Document, UUID(items[0]['id']))
        doc.title = '改名后的价格表'; db.session.commit()
    updated = client.get(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin).json['data']['items'][0]
    assert updated['reference']['expected_documents'] == ['改名后的价格表']
    assert updated['reference']['expected_document_ids'] == example['reference']['expected_document_ids']
    with app.app_context():
        doc = db.session.get(Document, UUID(items[0]['id']))
        doc.status = 'deleted'; db.session.commit()
    assert not client.get(endpoint, headers=admin).json['data']['items']
    assert client.get(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin).json['data']['items'][0]['document_issue']
    assert client.post(f"/api/v1/evaluations/examples/{example['id']}/review", headers=admin,
        json={'expected_revision': 1, 'confirmed': True}).status_code == 422
    assert client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '过期文档', 'reviewed_only': False}).status_code == 422


def test_document_metrics_use_ids_despite_duplicate_or_changed_titles():
    from app.application.qa.evaluation import metrics
    reference = {'expected_document_ids': ['correct'], 'expected_documents': ['旧标题']}
    output = {'retrieved_document_ids': ['wrong', 'correct'], 'retrieved_documents': ['相同标题', '相同标题'],
              'cited_document_ids': ['wrong'], 'cited_documents': ['旧标题']}
    scores = metrics(output, reference)
    assert scores['document_recall_at_10'] == 1
    assert scores['document_mrr'] == .5
    assert scores['citation_document_precision'] == 0


def test_document_id_migration_preserves_exact_matches_and_flags_ambiguous(app, dataset, monkeypatch):
    import importlib.util
    from pathlib import Path

    from app.entities import EvaluationDataset, EvaluationExample, now
    path = Path(__file__).parents[1] / 'migrations/versions/d31f9a827c60_evaluation_document_ids.py'
    spec = importlib.util.spec_from_file_location('document_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with app.app_context():
        original = db.session.get(EvaluationExample, UUID(dataset[1]['id']))
        reviewer = original.created_by
        original.reference = {'expected_documents': ['价格表']}
        original.reviewed_by, original.reviewed_at = reviewer, now()
        base_id = db.session.get(EvaluationDataset, original.dataset_id).knowledge_base_id
        db.session.add_all([Document(title='同名文件', knowledge_base_id=base_id) for _ in range(2)])
        ambiguous = EvaluationExample(dataset_id=original.dataset_id, name='同名问题', inputs=original.inputs,
            reference={'expected_documents': ['同名文件']}, reviewed_by=reviewer, reviewed_at=now())
        missing = EvaluationExample(dataset_id=original.dataset_id, name='过期问题', inputs=original.inputs,
            reference={'expected_documents': ['已不存在']}, reviewed_by=reviewer, reviewed_at=now())
        db.session.add_all([ambiguous, missing]); db.session.flush()
        monkeypatch.setattr(migration.op, 'get_bind', lambda: db.session.connection())
        migration.upgrade()
        db.session.expire_all()
        assert original.reference['expected_document_ids'] == dataset[1]['reference']['expected_document_ids']
        assert original.reviewed_by == reviewer and original.revision == 2
        assert ambiguous.reviewed_by is None and missing.reviewed_by is None
        assert ambiguous.reference['expected_documents'] == ['同名文件']


def test_save_and_enable_is_atomic_and_edit_can_return_to_draft(app, client, admin, dataset):
    did, example, payload = dataset
    endpoint = f"/api/v1/evaluations/examples/{example['id']}"
    enabled = client.put(endpoint, headers=admin, json={**payload, 'expected_revision': 1, 'status': 'enabled'})
    assert enabled.status_code == 200
    enabled = enabled.json['data']
    assert enabled['status'] == 'enabled' and enabled['reviewed_by'] and enabled['reviewed_at']
    assert enabled['revision'] == 2
    run = client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '直接使用启用的题目'})
    assert run.status_code == 202 and run.json['data']['total'] == 1
    draft = client.put(endpoint, headers=admin, json={**payload, 'expected_revision': 2, 'status': 'draft'}).json['data']
    assert draft['status'] == 'draft' and not draft['reviewed_by'] and draft['revision'] == 3
    assert client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '没有启用题目'}).status_code == 422
    assert client.put(endpoint, headers=admin,
        json={**payload, 'expected_revision': 2, 'status': 'enabled'}).status_code == 409
    for status in ['invalid', True, None]:
        assert client.put(endpoint, headers=admin,
            json={**payload, 'expected_revision': 3, 'status': status}).status_code == 422
    assert client.get(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin).json['data']['items'][0]['revision'] == 3
    incomplete = {**payload, 'name': '未完成标注', 'reference': {}}
    assert client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
        json={**incomplete, 'status': 'enabled'}).status_code == 422
    draft = client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin, json=incomplete)
    assert draft.status_code == 201 and draft.json['data']['status'] == 'draft'
    assert client.post(f'/api/v1/evaluations/datasets/{did}/examples', headers=admin,
        json={**payload, 'name': '新题直接启用', 'status': 'enabled'}).json['data']['status'] == 'enabled'


@pytest.mark.parametrize('extension', ['.docx', '.xlsx', '.txt', '.pdf'])
def test_evaluation_document_previews_use_real_parsers_and_scoped_storage(app, client, admin, dataset, monkeypatch, extension):
    from io import BytesIO
    from app.application.documents import preview

    did, example, _ = dataset
    doc_id = example['reference']['expected_document_ids'][0]
    if extension == '.docx':
        from docx import Document as WordDocument
        doc = WordDocument(); doc.add_heading('产品介绍', 1); doc.add_paragraph('票价99元')
        output = BytesIO(); doc.save(output); content = output.getvalue()
    elif extension == '.xlsx':
        from openpyxl import Workbook
        book = Workbook(); book.active.append(['票价', 99]); output = BytesIO(); book.save(output); content = output.getvalue()
    else:
        content = '票价99元'.encode()
    with app.app_context():
        version = db.session.scalar(db.select(DocumentVersion).where(DocumentVersion.document_id == UUID(doc_id)))
        version.filename = 'price' + extension; db.session.commit()
    reads, signed = [], []
    monkeypatch.setattr(preview, 'read_object', lambda key, **kwargs: reads.append((key, kwargs)) or content)
    monkeypatch.setattr(preview, 'presign_get', lambda key, name, **kwargs: signed.append(kwargs) or 'https://example.test/preview')
    response = client.get(f'/api/v1/evaluations/datasets/{did}/documents/{doc_id}/preview', headers=admin)
    assert response.status_code == 200, response.json
    data = response.json['data']
    assert data['document']['id'] == doc_id and data['version']['filename'] == 'price' + extension
    if extension == '.docx': assert data['kind'] == 'word' and '票价99元' in data['html']
    if extension == '.xlsx': assert data['kind'] == 'excel' and data['workbook']['sheets'][0]['cells']['0,1']['value'] == 99
    if extension == '.txt': assert data['kind'] == 'text' and data['content'] == '票价99元'
    if extension == '.pdf': assert signed[0]['inline'] and data['kind'] == 'pdf' and not reads
    else: assert reads[0][0] == 'price' and reads[0][1]['bucket'] == 'test' and reads[0][1]['max_size'] > 0


def test_evaluation_preview_does_not_grant_document_management_or_other_base_access(app, client, admin, dataset, monkeypatch):
    from test_page_authorization import grant
    from app.application.documents import preview
    from app.entities import Role, RolePagePermission

    did, example, _ = dataset
    doc_id = example['reference']['expected_document_ids'][0]
    result = app.test_cli_runner().invoke(args=['create-user', '--username', 'curator'], input='Curator-Password-2026!\nCurator-Password-2026!\n')
    assert result.exit_code == 0
    curator = login(client, 'curator', 'Curator-Password-2026!')
    with app.app_context():
        role = db.session.scalar(db.select(Role).where(Role.code == 'user'))
        db.session.execute(db.delete(RolePagePermission).where(RolePagePermission.role_id == role.id)); db.session.commit()
        other_base = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.code == 'general'))
        foreign_doc = Document(title='其他知识库资料', knowledge_base_id=other_base.id)
        db.session.add(foreign_doc); db.session.commit(); foreign_id = str(foreign_doc.id)
    path = f'/api/v1/evaluations/datasets/{did}/documents/{doc_id}/preview'
    assert client.get(path, headers=curator).status_code == 403
    grant(app, '/evaluations')
    reads = []
    monkeypatch.setattr(preview, 'read_object', lambda *args, **kwargs: reads.append(1) or b'preview')
    assert client.get(path, headers=curator).status_code == 200 and len(reads) == 1
    assert client.get(f'/api/v1/documents/{doc_id}/content', headers=curator).status_code == 403
    assert client.post(f'/api/v1/documents/{doc_id}/excel-content', headers=curator, json={}).status_code == 403
    assert client.get(f'/api/v1/evaluations/datasets/{did}/documents/{foreign_id}/preview', headers=curator).status_code == 404
    with app.app_context():
        doc = db.session.get(Document, UUID(doc_id)); doc.status = 'archived'; db.session.commit()
    assert client.get(path, headers=curator).status_code == 404 and len(reads) == 1


def test_single_verdict_validation_and_release_gate(app, client, admin, dataset, monkeypatch):
    _, candidate = save(client, admin)
    run = approved_run(app, client, admin, dataset, monkeypatch, candidate['id'])
    endpoint = f"/api/v1/evaluations/runs/{run['id']}/reviews/{dataset[1]['id']}"
    review = run['results'][0]['review']
    assert 'baseline' not in review and review['candidate'] == 1 and review['note'] == ''
    assert review['reviewed_by'] and review['reviewed_at']
    assert run['summary']['human'] == {'baseline': None, 'candidate': 1}
    assert run['summary']['human_reviewed_count'] == 1
    for invalid in [{}, {'candidate': None}, {'candidate': True}, {'candidate': '1'},
                    {'candidate': 1.0}, {'candidate': 2}, {'candidate': -1},
                    {'candidate': 1, 'note': None}, {'candidate': 1, 'note': 'x' * 2001},
                    {'candidate': 1, 'note': '\x00'}, {'candidate': 1, 'baseline': True}]:
        response = client.post(endpoint, headers=admin, json=invalid)
        assert response.status_code == 422, response.json
    detail = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    assert detail['results'][0]['review'] == review
    response = client.post(endpoint, headers=admin, json={'candidate': 0, 'note': '  遗漏适用条件  '})
    assert response.status_code == 200
    rejected = response.json['data']
    assert rejected['results'][0]['review']['note'] == '遗漏适用条件'
    assert rejected['summary']['human'] == {'baseline': None, 'candidate': 0}
    assert '候选答案存在人工复核不合格项' in rejected['quality_reasons']
    check = '/api/v1/prompts/answer_robot/versions/2/release-check'
    assert not client.get(check, headers=admin).json['data']['eligible']
    publish = {'version': 2, 'expected_generation': 1, 'evaluation_run_id': run['id']}
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin, json=publish).status_code == 409
    assert client.post(endpoint, headers=admin, json={'candidate': 1}).status_code == 200
    assert client.get(check, headers=admin).json['data']['eligible']
    assert client.post('/api/v1/prompts/answer_robot/publish', headers=admin, json=publish).status_code == 200


def test_mixed_reviews_do_not_invent_baseline_ratings():
    pair = {'baseline': {'scores': {}, 'error': None}, 'candidate': {'scores': {}, 'error': None}}
    result = aggregate([
        {**pair, 'review': {'baseline': 0, 'candidate': 1}},
        {**pair, 'review': {'candidate': 0}},
        {**pair, 'review': None},
    ])
    assert result['human_reviewed_count'] == 2
    assert result['human'] == {'baseline': 0, 'candidate': 0.5}
    assert aggregate([])['human'] == {'baseline': None, 'candidate': None}


def test_single_verdict_cannot_approve_running_or_failed_answers(app, client, admin, dataset, monkeypatch):
    did, example, _ = dataset
    run = client.post('/api/v1/evaluations/runs', headers=admin,
        json={'dataset_id': did, 'name': '异常评测', 'reviewed_only': False}).json['data']
    endpoint = f"/api/v1/evaluations/runs/{run['id']}/reviews/{example['id']}"
    assert client.post(endpoint, headers=admin, json={'candidate': 1}).status_code == 409
    def fail(*args, **kwargs):
        raise TimeoutError('provider failed')
    monkeypatch.setattr(evaluation_worker, 'evaluate_input', fail)
    assert evaluation_worker.process_one(app)
    detail = client.get(f"/api/v1/evaluations/runs/{run['id']}", headers=admin).json['data']
    assert detail['status'] == 'FAILED' and detail['completed'] == detail['total'] == 1
    assert client.post(endpoint, headers=admin, json={'candidate': 1}).status_code == 409
