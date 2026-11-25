from app.extensions import db
from app.models import AuditLog, Page, Role, RolePagePermission, User


def login(client, username="admin", password="Test-Password-2026!"):
    data = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    ).get_json()["data"]
    return {"Authorization": f"Bearer {data['access_token']}"}


def test_dashboard_obeys_current_role_pages_and_only_returns_permitted_counts(app, client):
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    with app.app_context():
        role = db.session.scalar(db.select(Role).where(Role.code == "user"))
        pages = db.session.scalars(
            db.select(Page).where(
                Page.route_path.in_(["/dashboard", "/knowledge-bases"]),
            )
        ).all()
        for page in pages:
            db.session.add(RolePagePermission(role_id=role.id, page_id=page.id, can_view=True))
        db.session.commit()
        role_id = role.id
    headers = login(client, "reader", "Reader-Password-2026!")
    response = client.get("/api/v1/dashboard", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"] == {"knowledge_base_count": 1}
    # Permission changes must take effect even with an existing access token.
    with app.app_context():
        page = db.session.scalar(db.select(Page).where(Page.route_path == "/knowledge-bases"))
        page.status = "disabled"
        db.session.commit()
    assert client.get("/api/v1/dashboard", headers=headers).get_json()["data"] == {}
    with app.app_context():
        page = db.session.scalar(db.select(Page).where(Page.route_path == "/dashboard"))
        permission = db.session.scalar(
            db.select(RolePagePermission).where(
                RolePagePermission.page_id == page.id,
                RolePagePermission.role_id == role_id,
            )
        )
        permission.can_view = False
        db.session.commit()
    assert client.get("/api/v1/dashboard", headers=headers).status_code == 403


def test_audit_list_includes_operator_names_and_keeps_system_records(app, client):
    headers = login(client)
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.username == "admin"))
        user.display_name = "张三"
        db.session.add_all(
            [
                AuditLog(user_id=user.id, action="fixture.update", resource_type="user"),
                AuditLog(action="fixture.system", resource_type="system"),
            ]
        )
        db.session.commit()
    response = client.get("/api/v1/audit-logs?q=fixture", headers=headers)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 2
    names = {row["action"]: row["user_name"] for row in data["items"]}
    assert names == {"fixture.update": "张三", "fixture.system": "系统"}
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.username == "admin"))
        user.status = "deleted"
        db.session.commit()
    root_headers = login(client, "root", "Dexforce@Root2026!")
    items = client.get("/api/v1/audit-logs?q=fixture.update", headers=root_headers).get_json()[
        "data"
    ]["items"]
    assert items[0]["user_name"] == "张三"
