from uuid import uuid4

from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.application.documents.index_profile import build_index_profile, profile_hash
from app.application.qa.evaluation import metrics
from app.application.qa.observability import RunRecorder
from app.application.qa.reranker import rerank_sources
from app.integrations.ai.langchain_adapters import document_source, source_document
from app.processors.rag_documents import KnowledgeTextSplitter, excel_documents


def test_splitter_preserves_commands_and_table_headers():
    code = '```bash\n' + 'echo hello\n' * 200 + '```'
    table = '| 景点 | 地址 |\n| --- | --- |\n' + '| 景区 | 宜宾市区 |\n' * 180
    docs = KnowledgeTextSplitter().create_documents(['# 操作\n\n' + code + '\n\n# 景点\n\n' + table], [{'version_id': 'v1'}])
    assert all(isinstance(d, Document) for d in docs)
    assert any(code in d.page_content for d in docs)
    table_docs = [d for d in docs if '| 景区 |' in d.page_content]
    assert len(table_docs) > 1
    assert all('| 景点 | 地址 |' in d.page_content for d in table_docs)
    assert all(d.metadata['section_id'] and d.metadata['version_id'] == 'v1' for d in docs)
    assert {d.metadata['heading_path'] for d in docs} == {'操作', '景点'}


def test_excel_rows_keep_sheet_header_and_original_location():
    docs = excel_documents({'sheets': [{'id': 's', 'name': '门票', 'cells': {
        '0,0': {'value': '景点'}, '0,1': {'value': '价格'},
        '3,0': {'value': '蜀南竹海'}, '3,1': {'value': 99},
    }}]}, version_id='v')
    assert len(docs) == 2
    assert '景点' in docs[1].page_content and '蜀南竹海' in docs[1].page_content
    assert docs[1].metadata['sheet'] == '门票' and docs[1].metadata['row_start'] == 4


def test_profile_hash_and_citation_document_roundtrip():
    one = build_index_profile(embedding_model='test', dimension=1024)
    assert profile_hash(one) == profile_hash(dict(reversed(list(one.items()))))
    assert profile_hash(one) != profile_hash({**one, 'embedding_dimension': 2048})
    source = {'content': '资料', 'chunk_id': str(uuid4()), 'version_id': str(uuid4()),
              'source_id': '1', 'document_title': '景点', 'preview_url': 'private'}
    assert document_source(source_document(source)) == {k: v for k, v in source.items() if k != 'preview_url'}


def test_rerank_unavailable_preserves_all_candidates_with_fallback(app, monkeypatch):
    from app.application.qa.reranker import DashScopeReranker
    def fail(*args):
        raise TimeoutError()
    monkeypatch.setattr(DashScopeReranker, 'rank', fail)
    app.config['QA_RERANK_PROVIDER'] = 'dashscope'
    with app.app_context():
        result = rerank_sources('question', [{'chunk_id': 'a'}, {'chunk_id': 'b'}])
    assert [s['chunk_id'] for s in result] == ['a', 'b']
    assert all(s['rerank_fallback'] for s in result)


def test_local_recorder_keeps_parent_links_and_usage_without_content():
    recorder = RunRecorder()
    root, model = uuid4(), uuid4()
    recorder.on_chain_start(None, {'secret question': 'content'}, run_id=root, name='rag.turn')
    recorder.on_chat_model_start({'name': 'fake'}, [], run_id=model, parent_run_id=root)
    response = LLMResult(generations=[[ChatGeneration(message=AIMessage(content='private answer',
        usage_metadata={'input_tokens': 10, 'output_tokens': 4, 'total_tokens': 14}))]])
    recorder.on_llm_end(response, run_id=model)
    recorder.on_chain_end({}, run_id=root)
    assert recorder.usage == {'input_tokens': 10, 'output_tokens': 4}
    assert recorder.steps[1]['parent_id'] == str(root)
    assert all(s['status'] == 'success' for s in recorder.steps)
    assert 'private answer' not in str(recorder.steps) and 'secret question' not in str(recorder.steps)


def test_evaluation_uses_explicit_gold_labels():
    actual = {'retrieved_documents': ['A', 'A', 'B'], 'cited_documents': ['B'],
              'answer': '开放时间九点', 'status': 'SUCCESS'}
    scores = metrics(actual, {'expected_documents': ['B', 'C'],
                             'answer_points': ['九点', '免费'], 'expected_status': 'SUCCESS'})
    assert scores['document_recall_at_10'] == .5
    assert scores['document_mrr'] == .5
    assert scores['answer_point_literal_coverage'] == .5
    assert metrics(actual, {}) == {}


def test_excel_title_row_does_not_replace_real_column_headers():
    docs = excel_documents({'sheets': [{'id': 's', 'name': '产品', 'cells': {
        '0,0': {'value': '景区套票产品'},
        '1,0': {'value': '产品名称'}, '1,1': {'value': '产品价格'},
        '2,0': {'value': '地质科普游'}, '2,1': {'value': '99元/人'},
    }}]}, version_id='v')
    assert len(docs) == 2
    assert '产品价格: 99元/人' in docs[1].page_content
    assert '景区套票产品' in docs[1].page_content
    assert docs[1].metadata['header_row'] == 2
    assert docs[1].metadata['row_start'] == 3


def test_word_numbered_headings_survive_extraction_for_section_retrieval():
    from io import BytesIO
    from docx import Document as WordDocument
    from app.workers.index_worker import _extract_text
    word = WordDocument()
    word.add_paragraph('一、交通指南')
    word.add_paragraph('停车四小时10元。')
    word.add_paragraph('二、景区票务')
    word.add_paragraph('成人门票80元。')
    output = BytesIO(); word.save(output)
    chunks = KnowledgeTextSplitter().create_documents([_extract_text('guide.docx', output.getvalue())])
    assert len(chunks) == 2
    assert chunks[0].metadata['heading_path'] == '一、交通指南'
    assert chunks[1].metadata['heading_path'] == '二、景区票务'
