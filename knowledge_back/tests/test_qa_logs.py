from uuid import uuid4

from app.extensions import db
from app.models import KnowledgeBase, QALog, User


def admin_headers(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Test-Password-2026!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.get_json()['data']['access_token']}"}


def test_admin_can_view_qa_log_detail_with_answer_and_sources(app, client):
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.username == "admin"))
        base = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.code == "general"))
        log = QALog(
            id=uuid4(),
            request_id="detail-test-request",
            source_type="WEB",
            user_id=user.id,
            knowledge_base_id=base.id,
            question="如何配置设备？",
            answer="请先检查电源，再完成初始化。",
            sources=[
                {
                    "source_id": "1",
                    "document_title": "设备手册",
                    "heading_path": "初始化",
                    "content": "检查电源并完成初始化。",
                    "modality": "text",
                    "score": 0.91,
                }
            ],
            retrieval_count=3,
            model_name="test-chat",
            status="SUCCESS",
            latency_ms=420,
        )
        db.session.add(log)
        db.session.commit()
        log_id = str(log.id)

    response = client.get(f"/api/v1/qa-logs/{log_id}", headers=admin_headers(client))
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["question"] == "如何配置设备？"
    assert data["answer"] == "请先检查电源，再完成初始化。"
    assert data["knowledge_base_name"] == "通用知识库"
    assert data["user_name"] == "admin"
    assert data["sources"][0]["document_title"] == "设备手册"
    assert data["latency_ms"] == 420


def test_qa_log_detail_requires_admin_and_returns_not_found(client):
    response = client.get(f"/api/v1/qa-logs/{uuid4()}")
    assert response.status_code == 401
    headers = admin_headers(client)
    response = client.get(f"/api/v1/qa-logs/{uuid4()}", headers=headers)
    assert response.status_code == 404
