from uuid import UUID, uuid4

import test_document_creation as creation_tests
from test_document_creation import create, word_content
from test_qa_logs import admin_headers
from test_word_editing import grant_documents

from app.extensions import db
from app.models import AuditLog, Page, Role, RolePagePermission, User

authoring_setup = creation_tests.creation


def test_lists_show_creator_and_last_editor_display_names(app, client, authoring_setup):
    grant_documents(app)
    with app.app_context():
        admin = db.session.scalar(db.select(User).where(User.username == "admin"))
        writer = db.session.scalar(db.select(User).where(User.username == "writer"))
        admin.display_name, writer.display_name = "创建者张三", "编辑者李四"
        writer_id = writer.id
        role = db.session.scalar(db.select(Role).where(Role.code == "user"))
        page = db.session.scalar(db.select(Page).where(Page.route_path == "/knowledge-bases"))
        db.session.add(RolePagePermission(role_id=role.id, page_id=page.id, can_view=True))
        db.session.commit()
    admin_auth, writer_auth = admin_headers(client), authoring_setup["headers"]
    base = client.post(
        "/api/v1/knowledge-bases", headers=admin_auth, json={"code": "names", "name": "人员测试库"}
    ).get_json()["data"]
    assert base["created_by_name"] == base["updated_by_name"] == "创建者张三"
    updated = client.put(
        f"/api/v1/knowledge-bases/{base['id']}", headers=writer_auth, json={"name": "人员查询库"}
    )
    assert updated.get_json()["data"]["updated_by_name"] == "编辑者李四"
    listed = client.get("/api/v1/knowledge-bases?q=人员查询", headers=admin_auth).get_json()[
        "data"
    ]["items"]
    assert len(listed) == 1
    assert listed[0]["created_by_name"] == "创建者张三"
    assert listed[0]["updated_by_name"] == "编辑者李四"

    response, _ = create(
        client, authoring_setup, knowledge_base_id=base["id"], format="docx", content=word_content()
    )
    document = response.get_json()["data"]
    doc_id, version_id = document["document"]["id"], document["version"]["id"]
    assert document["document"]["created_by_name"] == "编辑者李四"
    result = client.post(
        f"/api/v1/documents/{doc_id}/word-content",
        headers=admin_auth,
        json={"base_version_id": version_id, "content": word_content(), "request_id": str(uuid4())},
    )
    assert result.status_code == 201
    assert result.get_json()["data"]["document"]["updated_by_name"] == "创建者张三"
    with app.app_context():
        # Reindex and preparation are not changes to the document's content.
        for action in ("document.reindex", "document.upload.prepare"):
            db.session.add(
                AuditLog(
                    user_id=writer_id,
                    action=action,
                    resource_type="document",
                    resource_id=UUID(doc_id),
                    detail={},
                )
            )
        db.session.commit()
    for url in (f"/api/v1/knowledge-bases/{base['id']}/documents?q=设备指南", "/api/v1/documents"):
        items = client.get(url, headers=admin_auth).get_json()["data"]["items"]
        item = next(i for i in items if i["id"] == doc_id)
        assert item["created_by_name"] == "编辑者李四"
        assert item["updated_by_name"] == "创建者张三"
    with app.app_context():
        writer = db.session.get(User, writer_id)
        writer.display_name = "李四的新显示名称"
        db.session.commit()
    detail = client.get(f"/api/v1/documents/{doc_id}", headers=admin_auth).get_json()["data"]
    assert detail["created_by_name"] == "李四的新显示名称"
    assert detail["updated_by_name"] == "创建者张三"
