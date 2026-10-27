from uuid import UUID

from app.extensions import db
from app.models import AuditLog, Page, Role


def login(client, username="admin", password="Test-Password-2026!"):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.get_json()['data']['access_token']}"}


def page_ids(app, *codes):
    with app.app_context():
        pages = db.session.scalars(db.select(Page).where(Page.code.in_(codes))).all()
        return {page.code: str(page.id) for page in pages}


def role_id(app, code):
    with app.app_context():
        return str(db.session.scalar(db.select(Role.id).where(Role.code == code)))


def test_admin_can_replace_role_pages_and_login_uses_the_new_set(app, client):
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    ids = page_ids(app, "knowledge_qa", "profile", "dashboard")
    role = role_id(app, "user")
    headers = login(client)

    response = client.put(
        f"/api/v1/roles/{role}/pages",
        headers=headers,
        json={"page_ids": [ids["dashboard"], ids["profile"]]},
    )
    assert response.status_code == 200
    assert set(response.get_json()["data"]["page_ids"]) == {ids["dashboard"], ids["profile"]}

    queried = client.get(f"/api/v1/roles/{role}/pages", headers=headers)
    assert queried.status_code == 200
    assert set(queried.get_json()["data"]["page_ids"]) == {ids["dashboard"], ids["profile"]}

    reader = client.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "Reader-Password-2026!"},
    )
    assert reader.status_code == 200
    assert {page["route_path"] for page in reader.get_json()["data"]["pages"]} == {
        "/dashboard",
        "/profile",
    }

    with app.app_context():
        audit = db.session.scalar(
            db.select(AuditLog)
            .where(
                AuditLog.action == "role.permissions.update",
                AuditLog.resource_id == UUID(role),
            )
            .order_by(AuditLog.created_at.desc())
        )
        assert audit is not None
        assert set(audit.detail["after_page_ids"]) == {ids["dashboard"], ids["profile"]}


def test_role_pages_reject_invalid_ids_allow_empty_and_require_admin(app, client):
    role = role_id(app, "user")
    headers = login(client)
    endpoint = f"/api/v1/roles/{role}/pages"

    for body in [{}, {"page_ids": "not-an-array"}, {"page_ids": ["bad-uuid"]}]:
        assert client.put(endpoint, headers=headers, json=body).status_code == 422

    ids = page_ids(app, "profile")
    assert client.put(endpoint, headers=headers, json={"page_ids": [ids["profile"], ids["profile"]]}).status_code == 422
    assert client.put(
        endpoint,
        headers=headers,
        json={"page_ids": ["00000000-0000-0000-0000-000000000000"]},
    ).status_code == 422
    assert client.put(endpoint, headers=headers, json={"page_ids": []}).status_code == 200
    assert client.get(endpoint, headers=headers).get_json()["data"]["page_ids"] == []

    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    reader = client.post(
        "/api/v1/auth/login",
        json={"username": "reader", "password": "Reader-Password-2026!"},
    ).get_json()["data"]
    reader_headers = {"Authorization": f"Bearer {reader['access_token']}"}
    assert client.get(endpoint, headers=reader_headers).status_code == 403
    assert client.put(endpoint, headers=reader_headers, json={"page_ids": []}).status_code == 403


def test_super_admin_cannot_remove_active_pages(app, client):
    admin_role = role_id(app, "super_admin")
    headers = login(client)
    response = client.put(
        f"/api/v1/roles/{admin_role}/pages",
        headers=headers,
        json={"page_ids": []},
    )
    assert response.status_code == 403
