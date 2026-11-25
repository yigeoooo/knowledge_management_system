def login(client, username="admin", password="Test-Password-2026!"):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.get_json()['data']['access_token']}"}


def test_admin_can_create_update_and_archive_knowledge_base(app, client):
    headers = login(client)
    created = client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"code": "manuals", "name": "产品手册", "description": "发布文档"},
    )
    assert created.status_code == 201
    base = created.get_json()["data"]
    assert base["status"] == "active"
    assert base["created_by"]

    duplicate = client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"code": "manuals", "name": "重复编码"},
    )
    assert duplicate.status_code == 409

    updated = client.put(
        f"/api/v1/knowledge-bases/{base['id']}",
        headers=headers,
        json={"name": "产品使用手册", "description": "更新后的说明", "status": "disabled"},
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["status"] == "disabled"

    archived = client.delete(f"/api/v1/knowledge-bases/{base['id']}", headers=headers)
    assert archived.status_code == 200
    assert archived.get_json()["data"]["status"] == "archived"
    detail = client.get(f"/api/v1/knowledge-bases/{base['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.get_json()["data"]["status"] == "archived"

    audit = client.get("/api/v1/audit-logs?q=knowledge_base", headers=headers)
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.get_json()["data"]["items"]}
    assert {"knowledge_base.create", "knowledge_base.update", "knowledge_base.archive"} <= actions


def test_regular_user_only_sees_active_knowledge_bases_and_cannot_manage_them(app, client):
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0, result.output
    admin_headers = login(client)
    created = client.post(
        "/api/v1/knowledge-bases",
        headers=admin_headers,
        json={"code": "temporary", "name": "临时知识库"},
    )
    assert created.status_code == 201
    base_id = created.get_json()["data"]["id"]

    reader_headers = login(client, "reader", "Reader-Password-2026!")
    visible = client.get("/api/v1/knowledge-bases", headers=reader_headers)
    assert visible.status_code == 200
    assert "temporary" in {item["code"] for item in visible.get_json()["data"]["items"]}
    assert client.get(f"/api/v1/knowledge-bases/{base_id}", headers=reader_headers).status_code == 200
    assert client.post(
        "/api/v1/knowledge-bases",
        headers=reader_headers,
        json={"code": "forbidden", "name": "无权限"},
    ).status_code == 403

    client.delete(f"/api/v1/knowledge-bases/{base_id}", headers=admin_headers)
    visible = client.get("/api/v1/knowledge-bases", headers=reader_headers)
    assert "temporary" not in {item["code"] for item in visible.get_json()["data"]["items"]}
    assert client.get(f"/api/v1/knowledge-bases/{base_id}", headers=reader_headers).status_code == 404
    assert client.get(
        f"/api/v1/knowledge-bases/{base_id}/documents", headers=admin_headers
    ).status_code == 409
