def test_login_returns_current_user_and_allowed_pages(client):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Test-Password-2026!",
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["request_id"]
    data = body["data"]
    assert data["user"]["username"] == "admin"
    assert {p["route_path"] for p in data["pages"]} == {
        "/dashboard",
        "/qa",
        "/profile",
        "/knowledge-bases",
        "/documents",
        "/robots",
        "/users",
        "/roles",
        "/pages",
        "/role-permissions",
        "/qa-logs",
        "/audit-logs",
    }
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200
    assert me.get_json()["data"]["user"]["id"] == data["user"]["id"]


def test_refresh_rotates_cookie_and_logout_revokes_access(client):
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Test-Password-2026!",
        },
    )
    cookie = client.get_cookie("kbs_refresh", path="/api/v1/auth")
    assert cookie.http_only and cookie.same_site == "Strict"
    old_cookie = cookie.value
    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 200
    token = response.get_json()["data"]["access_token"]
    assert client.get_cookie("kbs_refresh", path="/api/v1/auth").value != old_cookie
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/auth/logout", headers=headers, json={}).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={}).status_code == 401
    old_token = login.get_json()["data"]["access_token"]
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code
        == 401
    )


def test_regular_user_can_read_knowledge_bases_but_not_admin_dashboard(app, client):
    result = app.test_cli_runner().invoke(
        args=["create-user", "--username", "reader"],
        input="Reader-Password-2026!\nReader-Password-2026!\n",
    )
    assert result.exit_code == 0
    assert client.get("/api/v1/dashboard").status_code == 401
    assert client.get("/api/v1/knowledge-bases").status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "reader",
            "password": "Reader-Password-2026!",
        },
    ).get_json()["data"]
    assert {p["route_path"] for p in login["pages"]} == {"/qa", "/profile"}
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/v1/dashboard", headers=headers).status_code == 403
    bases = client.get("/api/v1/knowledge-bases", headers=headers)
    assert bases.status_code == 200
    assert [base["code"] for base in bases.get_json()["data"]["items"]] == ["general"]
    admin = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Test-Password-2026!",
        },
    ).get_json()["data"]
    dashboard = client.get(
        "/api/v1/dashboard", headers={"Authorization": f"Bearer {admin['access_token']}"}
    )
    assert dashboard.status_code == 200
    assert dashboard.get_json()["data"]["knowledge_base_count"] == 1


def test_root_has_all_pages_and_management_lists_exclude_credentials(app, client):
    result = client.post(
        "/api/v1/auth/login",
        json={
            "username": "root",
            "password": "Dexforce@Root2026!",
        },
    ).get_json()["data"]
    headers = {"Authorization": f"Bearer {result['access_token']}"}
    pages = client.get("/api/v1/pages", headers=headers)
    assert pages.status_code == 200
    assert len(result["pages"]) == pages.get_json()["data"]["total"] == 12
    users = client.get("/api/v1/users", headers=headers)
    assert users.status_code == 200
    assert "password" not in users.get_data(as_text=True)
    for path in ["/documents", "/robots", "/roles", "/qa-logs", "/audit-logs"]:
        assert client.get(f"/api/v1{path}", headers=headers).status_code == 200
        assert app.test_client().get(f"/api/v1{path}").status_code == 401


def test_invalid_credentials_and_malformed_requests_never_create_a_session(client):
    for username, password in [("admin", "wrong"), ("missing", "Test-Password-2026!")]:
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 401
        assert response.get_json()["message"] == "用户名或密码错误"
        assert client.get_cookie("kbs_refresh", path="/api/v1/auth") is None
    for body in [[], {}, {"username": 123, "password": "x"}]:
        assert client.post("/api/v1/auth/login", json=body).status_code == 422


def test_refresh_cookie_cannot_be_replayed_or_sent_from_another_site(app, client):
    client.post("/api/v1/auth/login", json={"username": "root", "password": "Dexforce@Root2026!"})
    old_cookie = client.get_cookie("kbs_refresh", path="/api/v1/auth").value
    assert (
        client.post(
            "/api/v1/auth/refresh", json={}, headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )
    assert client.post("/api/v1/auth/refresh", data={}).status_code == 403
    assert client.post("/api/v1/auth/refresh", json={}).status_code == 200
    replay = app.test_client()
    replay.set_cookie("kbs_refresh", old_cookie, path="/api/v1/auth")
    assert replay.post("/api/v1/auth/refresh", json={}).status_code == 401


def test_password_reset_invalidates_existing_session_and_old_password(app, client):
    login = client.post(
        "/api/v1/auth/login", json={"username": "root", "password": "Dexforce@Root2026!"}
    )
    token = login.get_json()["data"]["access_token"]
    result = app.test_cli_runner().invoke(
        args=["set-password", "--username", "root"],
        input="Updated-Password-2026!\nUpdated-Password-2026!\n",
    )
    assert result.exit_code == 0
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )
    assert client.post("/api/v1/auth/refresh", json={}).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "root", "password": "Dexforce@Root2026!"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "root", "password": "Updated-Password-2026!"}
        ).status_code
        == 200
    )
