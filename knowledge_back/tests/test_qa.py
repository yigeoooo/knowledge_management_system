"""Q&A endpoint contracts with isolated database and mocked model/storage services."""

import importlib
from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.extensions import db
from app.models import Document, DocumentChunk, DocumentVersion, KnowledgeBase, QALog, User, now

qa_module = importlib.import_module("app.qa")
retrieval_module = importlib.import_module("app.retrieval")
TEXTS = [
    "安装设备前请检查电源和接地，确认连接线完好后接通电源。设备启动完成时状态灯会亮起，此时可以开始操作。",
    "开发账号由管理员创建，申请时需要说明所属团队和用途。账号开通后应立即修改初始密码，再使用分配的权限访问平台。",
    "运行异常时先保存错误日志并记录发生时间，然后重新启动应用。若故障仍然存在，应携带日志联系维护人员协助排查。",
]
QUESTIONS = ["安装设备时需要检查什么？", "如何申请并启用开发账号？", "运行异常应该怎样排查？"]


def add_chunk(
    base_id,
    *,
    content=TEXTS[0],
    modality="text",
    current=True,
    status="INDEXED",
    document_status="active",
    model="test-embedding",
):
    document = Document(knowledge_base_id=base_id, title=content[:12], status=document_status)
    db.session.add(document)
    db.session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        filename="guide.txt",
        minio_bucket="test-bucket",
        minio_object_key=str(uuid4()),
        file_size=100,
        status=status,
        embedding_model=model,
    )
    db.session.add(version)
    db.session.flush()
    if current:
        document.current_version_id = version.id
    chunk = DocumentChunk(
        document_version_id=version.id,
        chunk_index=0,
        content=content,
        heading_path="使用说明",
        embedding=[1.0, 0.0],
        chunk_metadata={"modality": modality},
    )
    db.session.add(chunk)
    db.session.flush()
    return chunk


@pytest.fixture
def qa_setup(app, client, monkeypatch):
    app.config.update(DASHSCOPE_EMBEDDING_MODEL="test-embedding", QA_MIN_SIMILARITY=0.3)
    embedding = Mock(return_value=([1.0, 0.0], "test-embedding"))
    completion = Mock(side_effect=AssertionError("Unexpected model call"))
    monkeypatch.setattr(retrieval_module, "embed_query", embedding)
    monkeypatch.setattr(qa_module, "complete_json", completion)
    monkeypatch.setattr(
        retrieval_module, "presign_get", Mock(return_value="https://media.test/file")
    )
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "Test-Password-2026!"}
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.get_json()['data']['access_token']}"}
    with app.app_context():
        base = KnowledgeBase(code="qa-fixture", name="问答测试")
        other = KnowledgeBase(code="qa-other", name="其他知识库")
        db.session.add_all([base, other])
        db.session.flush()
        chunks = [str(add_chunk(base.id, content=text).id) for text in TEXTS]
        base_id, other_id = str(base.id), str(other.id)
        db.session.commit()
    return {
        "headers": headers,
        "base_id": base_id,
        "other_id": other_id,
        "chunks": chunks,
        "embedding": embedding,
        "completion": completion,
    }


def suggest(client, setup, **values):
    return client.post(
        "/api/v1/web/suggested-questions",
        headers=setup["headers"],
        json={"knowledge_base_id": setup["base_id"], **values},
    )


def ask(client, setup, **values):
    return client.post(
        "/api/v1/web/query",
        headers=setup["headers"],
        json={
            "knowledge_base_id": setup["base_id"],
            "question": QUESTIONS[0],
            "request_id": "qa-request-1",
            **values,
        },
    )


def grounded_answer(_instruction, material, **_options):
    source = material["sources"][0]
    return {
        "answerable": True,
        "answer": f"{source['content']} [{source['source_id']}]",
        "citations": [{"source_id": source["source_id"], "evidence": source["content"]}],
    }, "test-chat"


def test_suggestions_use_only_current_indexed_text_in_selected_base(app, client, qa_setup):
    with app.app_context():
        base_id = UUID(qa_setup["base_id"])
        for overrides in [
            {"current": False},
            {"status": "PROCESSING"},
            {"document_status": "archived"},
            {"modality": "image"},
            {"modality": "video"},
            {"model": "old-model"},
        ]:
            add_chunk(
                base_id,
                content="这些是不能出现在推荐问题中的旧版本、非文本或尚未索引的资料。" * 3,
                **overrides,
            )
        add_chunk(UUID(qa_setup["other_id"]))
        db.session.commit()

    def generate(_instruction, material, **_options):
        assert {source["chunk_id"] for source in material["sources"]} == set(qa_setup["chunks"])
        return {
            "questions": [
                {
                    "question": QUESTIONS[TEXTS.index(source["content"])],
                    "source_id": source["source_id"],
                    "evidence": source["content"],
                }
                for source in material["sources"]
            ]
        }, "test-chat"

    qa_setup["completion"].side_effect = generate
    response = suggest(client, qa_setup)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "ready"
    assert {item["question"] for item in data["questions"]} == set(QUESTIONS)
    qa_setup["completion"].assert_called_once()
    qa_setup["embedding"].assert_not_called()
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(QALog)) == 0


def test_empty_suggestions_do_not_call_model(client, qa_setup):
    response = suggest(client, qa_setup, knowledge_base_id=qa_setup["other_id"])
    assert response.status_code == 200
    assert response.get_json()["data"]["questions"] == []
    assert response.get_json()["data"]["status"] == "empty"
    qa_setup["completion"].assert_not_called()


def test_suggestions_drop_duplicate_questions_and_unverified_evidence(client, qa_setup):
    def generate(_instruction, material, **_options):
        sources = material["sources"]
        return {
            "questions": [
                {
                    "question": QUESTIONS[0],
                    "source_id": sources[0]["source_id"],
                    "evidence": sources[0]["content"],
                },
                {
                    "question": QUESTIONS[0],
                    "source_id": sources[1]["source_id"],
                    "evidence": sources[1]["content"],
                },
                {
                    "question": QUESTIONS[2],
                    "source_id": sources[2]["source_id"],
                    "evidence": "正文里完全不存在的引用",
                },
            ]
        }, "test-chat"

    qa_setup["completion"].side_effect = generate
    response = suggest(client, qa_setup)
    assert response.status_code == 200
    assert len(response.get_json()["data"]["questions"]) == 1


def test_query_replay_uses_one_generation_and_one_log(app, client, qa_setup):
    qa_setup["completion"].side_effect = grounded_answer
    first = ask(client, qa_setup)
    second = ask(client, qa_setup)
    assert first.status_code == second.status_code == 200
    data = first.get_json()["data"]
    assert second.get_json()["data"] == data
    assert data["answer_status"] == "answered"
    assert data["sources"][0]["chunk_id"] in qa_setup["chunks"]
    assert data["sources"][0]["source_id"] == "1"
    qa_setup["completion"].assert_called_once()
    qa_setup["embedding"].assert_called_once()
    with app.app_context():
        logs = db.session.scalars(db.select(QALog)).all()
        assert len(logs) == 1
        assert logs[0].status == "SUCCESS"
        assert logs[0].retrieval_count == 3


@pytest.mark.parametrize("invalid", ["unknown_source", "false_evidence", "missing_reference"])
def test_invalid_answer_citations_fail_and_can_retry_same_request(app, client, qa_setup, invalid):
    def generate(instruction, material, **options):
        payload, model = grounded_answer(instruction, material, **options)
        if invalid == "unknown_source":
            payload["citations"][0]["source_id"] = "999"
        elif invalid == "false_evidence":
            payload["citations"][0]["evidence"] = "没有出现在资料中的事实"
        else:
            payload["answer"] = "没有引用编号的回答"
        return payload, model

    qa_setup["completion"].side_effect = generate
    assert ask(client, qa_setup).status_code == 503
    with app.app_context():
        assert db.session.scalar(db.select(QALog)).status == "FAILED"
    qa_setup["completion"].side_effect = grounded_answer
    assert ask(client, qa_setup).status_code == 200
    with app.app_context():
        logs = db.session.scalars(db.select(QALog)).all()
        assert len(logs) == 1
        assert logs[0].status == "SUCCESS"
        assert logs[0].error_message is None


def test_low_similarity_skips_generation_and_records_insufficient_evidence(app, client, qa_setup):
    qa_setup["embedding"].return_value = ([-1.0, 0.0], "test-embedding")
    response = ask(client, qa_setup)
    assert response.status_code == 200
    assert response.get_json()["data"]["answer_status"] == "insufficient_evidence"
    assert response.get_json()["data"]["sources"] == []
    qa_setup["completion"].assert_not_called()
    with app.app_context():
        assert db.session.scalar(db.select(QALog)).status == "NO_EVIDENCE"


def test_media_only_returns_fresh_previews_without_generating_or_storing_urls(
    app,
    client,
    qa_setup,
    monkeypatch,
):
    with app.app_context():
        add_chunk(UUID(qa_setup["other_id"]), modality="image")
        db.session.commit()
    preview = Mock(side_effect=["https://media.test/first", "https://media.test/second"])
    monkeypatch.setattr(retrieval_module, "presign_get", preview)
    first = ask(client, qa_setup, knowledge_base_id=qa_setup["other_id"]).get_json()["data"]
    second = ask(client, qa_setup, knowledge_base_id=qa_setup["other_id"]).get_json()["data"]
    assert first["answer_status"] == "insufficient_evidence"
    assert first["sources"][0]["preview_url"] != second["sources"][0]["preview_url"]
    assert first["sources"][0]["content"] is None
    qa_setup["completion"].assert_not_called()
    with app.app_context():
        assert "preview_url" not in db.session.scalar(db.select(QALog)).sources[0]


@pytest.mark.parametrize("changed", ["question", "base", "actor"])
def test_request_id_cannot_be_reused_for_another_request(app, client, qa_setup, changed):
    qa_setup["completion"].side_effect = grounded_answer
    assert ask(client, qa_setup).status_code == 200
    values = {}
    if changed == "question":
        values["question"] = QUESTIONS[1]
    elif changed == "base":
        values["knowledge_base_id"] = qa_setup["other_id"]
    else:
        with app.app_context():
            root_id = db.session.scalar(db.select(User.id).where(User.username == "root"))
            assert root_id is not None
            db.session.scalar(db.select(QALog)).user_id = root_id
            db.session.commit()
    response = ask(client, qa_setup, **values)
    assert response.status_code == 409
    assert response.get_json()["code"] == 40901
    assert response.get_json()["data"] is None
    qa_setup["completion"].assert_called_once()


def test_processing_request_waits_then_stale_request_can_be_reclaimed(app, client, qa_setup):
    with app.app_context():
        user_id = db.session.scalar(db.select(User.id).where(User.username == "admin"))
        db.session.add(
            QALog(
                request_id="qa-request-1",
                source_type="WEB",
                user_id=user_id,
                knowledge_base_id=UUID(qa_setup["base_id"]),
                question=QUESTIONS[0],
                status="PROCESSING",
            )
        )
        db.session.commit()
    response = ask(client, qa_setup)
    assert response.status_code == 409
    assert response.get_json()["code"] == 40902
    qa_setup["embedding"].assert_not_called()
    with app.app_context():
        db.session.scalar(db.select(QALog)).updated_at = now() - timedelta(minutes=11)
        db.session.commit()
    qa_setup["completion"].side_effect = grounded_answer
    assert ask(client, qa_setup).status_code == 200


@pytest.mark.parametrize("during_generation", [True, False])
def test_archived_sources_in_new_or_replayed_answer_are_rejected(
    app,
    client,
    qa_setup,
    during_generation,
):
    def archive_sources():
        db.session.execute(
            db.update(Document)
            .where(Document.knowledge_base_id == UUID(qa_setup["base_id"]))
            .values(status="archived")
        )
        db.session.commit()

    def generate(instruction, material, **options):
        if during_generation:
            archive_sources()
        return grounded_answer(instruction, material, **options)

    qa_setup["completion"].side_effect = generate
    response = ask(client, qa_setup)
    if not during_generation:
        assert response.status_code == 200
        with app.app_context():
            archive_sources()
        response = ask(client, qa_setup)
    assert response.status_code == 409
    assert response.get_json()["code"] == 40903
    qa_setup["completion"].assert_called_once()


def test_superseded_request_cannot_overwrite_newer_attempt(app, client, qa_setup):
    def generate(instruction, material, **options):
        log = db.session.scalar(db.select(QALog))
        log.updated_at = now() + timedelta(seconds=1)
        log.answer = "由新请求维护"
        db.session.commit()
        return grounded_answer(instruction, material, **options)

    qa_setup["completion"].side_effect = generate
    response = ask(client, qa_setup)
    assert response.status_code == 409
    assert response.get_json()["code"] == 40902
    with app.app_context():
        log = db.session.scalar(db.select(QALog))
        assert log.status == "PROCESSING"
        assert log.answer == "由新请求维护"


@pytest.mark.parametrize("path", ["suggested-questions", "query"])
def test_qa_requires_auth_and_active_base(app, client, qa_setup, path):
    payload = (
        {
            "knowledge_base_id": qa_setup["base_id"],
            "question": QUESTIONS[0],
            "request_id": "request",
        }
        if path == "query"
        else {
            "knowledge_base_id": qa_setup["base_id"],
        }
    )
    assert client.post(f"/api/v1/web/{path}", json=payload).status_code == 401
    with app.app_context():
        db.session.get(KnowledgeBase, UUID(qa_setup["base_id"])).status = "disabled"
        db.session.commit()
    response = client.post(f"/api/v1/web/{path}", json=payload, headers=qa_setup["headers"])
    assert response.status_code == 404
    qa_setup["completion"].assert_not_called()
