from uuid import uuid4

import pytest

from app.extensions import db
from app.models import KnowledgeBase, Page, Role, RolePagePermission


def grant(app, *paths):
    with app.app_context():
        role = db.session.scalar(db.select(Role).where(Role.code == "user"))
        pages = db.session.scalars(db.select(Page).where(Page.route_path.in_(paths))).all()
        for page in pages:
            permission = db.session.get(RolePagePermission, (role.id, page.id))
            if permission:
                permission.can_view = True
            else:
                db.session.add(RolePagePermission(role_id=role.id, page_id=page.id, can_view=True))
        db.session.commit()


@pytest.fixture
def reader(app, client):
    app.config.update(INDEX_WORKER_AUTOSTART=False)
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "page-reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    with app.app_context():
        role = db.session.scalar(db.select(Role).where(Role.code == "user"))
        db.session.execute(
            db.delete(RolePagePermission).where(RolePagePermission.role_id == role.id)
        )
        db.session.commit()
    response = client.post(
        "/api/v1/auth/login", json={"username": "page-reader", "password": "Reader-Password-2026!"}
    )
    return {"Authorization": f"Bearer {response.get_json()['data']['access_token']}"}


@pytest.mark.parametrize(
    "path",
    [
        "/documents",
        "/robots",
        "/users",
        "/roles",
        "/pages",
        "/qa-logs",
        "/audit-logs",
        "/dashboard",
    ],
)
def test_granted_page_enables_its_api_and_revocation_takes_effect(app, client, reader, path):
    endpoint = f"/api/v1{path}"
    assert client.get(endpoint, headers=reader).status_code == 403
    grant(app, path)
    assert client.get(endpoint, headers=reader).status_code == 200
    with app.app_context():
        page = db.session.scalar(db.select(Page).where(Page.route_path == path))
        page.status = "disabled"
        db.session.commit()
    assert client.get(endpoint, headers=reader).status_code == 403


def test_assigned_management_page_allows_writes_without_opening_other_pages(app, client, reader):
    assert (
        client.post("/api/v1/robots", headers=reader, json={"serial_no": "R-1"}).status_code == 403
    )
    grant(app, "/robots", "/knowledge-bases")
    response = client.post(
        "/api/v1/robots", headers=reader, json={"serial_no": "R-1", "name": "设备"}
    )
    assert response.status_code == 201
    robot_id = response.get_json()["data"]["id"]
    assert (
        client.put(
            f"/api/v1/robots/{robot_id}", headers=reader, json={"name": "更新设备"}
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/robots/{robot_id}", headers=reader).status_code == 200
    response = client.post(
        "/api/v1/knowledge-bases",
        headers=reader,
        json={"code": "writer-base", "name": "新建资料库"},
    )
    assert response.status_code == 201
    assert client.post("/api/v1/users", headers=reader, json={}).status_code == 403
    assert client.post("/api/v1/roles", headers=reader, json={}).status_code == 403


def test_permissions_screen_can_read_options_and_save_grants_but_not_manage_roles(
    app, client, reader
):
    grant(app, "/role-permissions")
    assert client.get("/api/v1/roles", headers=reader).status_code == 200
    assert client.get("/api/v1/pages", headers=reader).status_code == 200
    assert client.post("/api/v1/roles", headers=reader, json={}).status_code == 403
    with app.app_context():
        role = db.session.scalar(db.select(Role).where(Role.code == "user"))
        role_id = str(role.id)
        pages = db.session.scalars(
            db.select(Page.id).where(Page.route_path.in_(["/role-permissions", "/documents"]))
        ).all()
        ids = [str(value) for value in pages]
    response = client.put(f"/api/v1/roles/{role_id}/pages", headers=reader, json={"page_ids": ids})
    assert response.status_code == 200
    assert client.get("/api/v1/documents", headers=reader).status_code == 200


def test_qa_requires_its_page_permission(app, client, reader):
    with app.app_context():
        base_id = str(db.session.scalar(db.select(KnowledgeBase.id)))
    body = {"knowledge_base_id": base_id}
    assert client.get('/api/v1/knowledge-bases', headers=reader).status_code == 403
    assert (
        client.post("/api/v1/web/suggested-questions", headers=reader, json=body).status_code == 403
    )
    grant(app, "/qa")
    assert client.get('/api/v1/knowledge-bases', headers=reader).status_code == 200
    assert (
        client.post("/api/v1/web/suggested-questions", headers=reader, json=body).status_code == 200
    )


def test_super_admin_bypasses_page_grants_and_receives_all_active_routes(app, client):
    with app.app_context():
        role = db.session.scalar(db.select(Role).where(Role.code == "super_admin"))
        db.session.execute(
            db.delete(RolePagePermission).where(RolePagePermission.role_id == role.id)
        )
        db.session.commit()
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "Test-Password-2026!"}
    )
    data = response.get_json()["data"]
    assert "/create-document" in {page["route_path"] for page in data["pages"]}
    assert len(data["pages"]) == 13
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/v1/users", headers=headers).status_code == 200
    assert (
        client.post("/api/v1/robots", headers=headers, json={"serial_no": str(uuid4())}).status_code
        == 201
    )
