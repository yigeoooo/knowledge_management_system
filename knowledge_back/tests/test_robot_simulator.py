from uuid import UUID, uuid4

import test_conversations as conversations
from test_knowledge_bases import login

from app.entities import Page, QALog, Robot, Role, RolePagePermission
from app.extensions import db

setup = conversations.setup


def test_simulator_menu_and_read_apis_are_admin_only_by_default(app, client, setup):
    admin = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Test-Password-2026!",
        },
    ).json["data"]
    assert any(p["code"] == "robot_qa" and p["name"] == "机器人问答" for p in admin["pages"])
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "sim-reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    reader = client.post(
        "/api/v1/auth/login",
        json={
            "username": "sim-reader",
            "password": "Reader-Password-2026!",
        },
    ).json["data"]
    assert all(p["code"] != "robot_qa" for p in reader["pages"])
    headers = {"Authorization": f"Bearer {reader['access_token']}"}
    for path in (
        "/admin/robot-chat/robots",
        f"/admin/robot-chat/robots/{setup['robot']}/conversations",
        f"/admin/robot-chat/robots/{setup['robot']}/conversations/{uuid4()}/turns",
    ):
        assert client.get("/api/v1" + path).status_code == 401
        assert client.get("/api/v1" + path, headers=headers).status_code == 403
    options = client.get("/api/v1/admin/robot-chat/robots", headers=setup["headers"])
    assert options.status_code == 200
    robot = options.json["data"]["items"][0]
    assert robot["serial_no"] == "conversation-robot"
    assert robot["knowledge_base_id"] == setup["base"]


def test_simulator_history_is_robot_scoped_and_returns_the_actual_plain_answer(app, client, setup):
    first = conversations.robot_first(client).json["data"]
    web = conversations.first(client, setup)
    with app.app_context():
        other = Robot(
            serial_no="other-simulator", knowledge_base_id=UUID(setup["base"]), binding_version=1
        )
        db.session.add(other)
        log = db.session.get(QALog, UUID(first["turn_id"]))
        log.answer = "**先检查电源**。\n\n[1]\n\n不要断开接地。\n\n[1]"
        log.sources = [{"source_id": "1"}]
        db.session.commit()
        other_id = str(other.id)
    root = f"/api/v1/admin/robot-chat/robots/{setup['robot']}/conversations"
    history = client.get(root, headers=setup["headers"]).json["data"]["items"]
    assert [c["id"] for c in history] == [first["conversation_id"]]
    detail = client.get(f"{root}/{first['conversation_id']}/turns", headers=setup["headers"])
    assert detail.status_code == 200
    turn = detail.json["data"]["items"][0]
    assert turn["answer"] == "先检查电源。 不要断开接地。"
    assert turn["sources"] == []
    assert (
        client.get(f"{root}/{web['conversation_id']}/turns", headers=setup["headers"]).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/admin/robot-chat/robots/{other_id}/conversations/{first['conversation_id']}/turns",
            headers=setup["headers"],
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/robot/conversations/{first['conversation_id']}",
            headers={"X-Robot-Serial": "conversation-robot"},
        ).status_code
        == 200
    )
    assert client.get(root, headers=setup["headers"]).json["data"]["items"] == []
    assert (
        client.get(f"{root}/{first['conversation_id']}/turns", headers=setup["headers"]).status_code
        == 404
    )


def test_simulator_can_read_closed_history_after_robot_rebinding(app, client, setup):
    first = conversations.robot_first(client).json["data"]
    assert (
        client.put(
            f"/api/v1/robots/{setup['robot']}",
            headers=setup["headers"],
            json={
                "knowledge_base_id": setup["other"],
                "expected_binding_version": 1,
            },
        ).status_code
        == 200
    )
    result = client.get(
        f"/api/v1/admin/robot-chat/robots/{setup['robot']}/conversations/{first['conversation_id']}/turns",
        headers=setup["headers"],
    )
    assert result.status_code == 200
    assert result.json["data"]["conversation"]["closed_at"]
    assert result.json["data"]["items"][0]["answer"] == "已核实的答案"


def test_existing_installation_migration_registers_menu_without_granting_regular_users(app, client):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["db", "downgrade", "6d8a2b1c904f"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        page = db.session.scalar(db.select(Page).where(Page.code == "robot_qa"))
        admin = db.session.scalar(db.select(Role).where(Role.code == "super_admin"))
        user = db.session.scalar(db.select(Role).where(Role.code == "user"))
        assert page.route_path == "/robot-qa" and page.component_key == "RobotQA"
        assert db.session.get(RolePagePermission, (admin.id, page.id)).can_view
        assert db.session.get(RolePagePermission, (user.id, page.id)) is None
    assert client.get("/api/v1/admin/robot-chat/robots", headers=login(client)).status_code == 200
