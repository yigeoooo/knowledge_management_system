from test_knowledge_bases import login


def test_admin_can_create_update_view_and_disable_robot(client):
    headers = login(client)
    created = client.post(
        "/api/v1/robots",
        headers=headers,
        json={
            "serial_no": "ROBOT-001",
            "name": "一号巡检机器人",
            "description": "仓库巡检设备",
        },
    )
    assert created.status_code == 201
    robot = created.get_json()["data"]
    assert robot["serial_no"] == "ROBOT-001"
    assert robot["status"] == "active"
    assert robot["created_by"]
    robot_id = robot["id"]

    duplicate = client.post(
        "/api/v1/robots",
        headers=headers,
        json={"serial_no": "ROBOT-001", "name": "重复设备"},
    )
    assert duplicate.status_code == 409

    detail = client.get(f"/api/v1/robots/{robot_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.get_json()["data"]["name"] == "一号巡检机器人"

    updated = client.put(
        f"/api/v1/robots/{robot_id}",
        headers=headers,
        json={"name": "二号巡检机器人", "description": "更新说明", "status": "disabled"},
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["status"] == "disabled"
    assert updated.get_json()["data"]["serial_no"] == "ROBOT-001"

    reenabled = client.put(
        f"/api/v1/robots/{robot_id}", headers=headers, json={"status": "active"}
    )
    assert reenabled.status_code == 200
    assert reenabled.get_json()["data"]["status"] == "active"

    deleted = client.delete(f"/api/v1/robots/{robot_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.get_json()["data"] == {"id": robot_id, "status": "disabled"}
    assert client.get(f"/api/v1/robots/{robot_id}", headers=headers).get_json()["data"]["status"] == "disabled"

    audit = client.get("/api/v1/audit-logs?q=robot", headers=headers)
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.get_json()["data"]["items"]}
    assert {"robot.create", "robot.update", "robot.delete"} <= actions


def test_robot_list_search_status_and_validation(client):
    headers = login(client)
    for serial, name, status in [
        ("ROBOT-A", "Alpha", "active"),
        ("ROBOT-B", "Beta", "disabled"),
    ]:
        assert client.post(
            "/api/v1/robots", headers=headers,
            json={"serial_no": serial, "name": name, "status": status},
        ).status_code == 201

    all_rows = client.get(
        "/api/v1/robots", headers=headers,
        query_string={"q": "ROBOT", "page_size": 100},
    )
    assert all_rows.status_code == 200
    assert all_rows.get_json()["data"]["total"] == 2

    active = client.get(
        "/api/v1/robots", headers=headers,
        query_string={"q": "Alpha", "status": "active"},
    )
    assert active.status_code == 200
    assert [item["serial_no"] for item in active.get_json()["data"]["items"]] == ["ROBOT-A"]

    for body in [{}, {"serial_no": ""}, {"serial_no": "ROBOT-C", "status": "invalid"}]:
        assert client.post("/api/v1/robots", headers=headers, json=body).status_code == 422
    assert client.get(
        "/api/v1/robots", headers=headers, query_string={"status": "invalid"}
    ).status_code == 422


def test_non_admin_cannot_manage_robots(app, client):
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    headers = login(client, "reader", "Reader-Password-2026!")
    assert client.get("/api/v1/robots", headers=headers).status_code == 403
    assert client.post(
        "/api/v1/robots", headers=headers, json={"serial_no": "ROBOT-X"}
    ).status_code == 403
