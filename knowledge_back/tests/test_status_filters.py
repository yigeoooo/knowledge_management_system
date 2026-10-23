import pytest

from app.extensions import db
from app.models import Document, KnowledgeBase, Page, QALog, Robot, Role, User


@pytest.fixture
def status_records(app):
    app.config["INDEX_WORKER_AUTOSTART"] = False
    with app.app_context():
        base = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.code == "general"))
        role = db.session.scalar(db.select(Role).where(Role.code == "user"))
        for status in ("active", "disabled", "archived"):
            db.session.add(
                KnowledgeBase(code=f"filter_{status}", name="Filter fixture", status=status)
            )
        for status in ("active", "disabled"):
            db.session.add_all(
                [
                    Role(code=f"filter_{status}", name="Filter fixture", status=status),
                    User(
                        username=f"filter_{status}",
                        display_name="Filter fixture",
                        password_hash="unused",
                        role_id=role.id,
                        status=status,
                    ),
                    Robot(serial_no=f"Filter fixture {status}", status=status),
                    Page(
                        code=f"filter_{status}",
                        name="Filter fixture",
                        status=status,
                        route_path=f"/filter-{status}",
                        route_name=f"filter_{status}",
                        component_key="PageManagement",
                    ),
                ]
            )
        db.session.add(
            User(
                username="filter_deleted",
                display_name="Filter fixture",
                password_hash="unused",
                role_id=role.id,
                status="deleted",
            )
        )
        for status in ("active", "archived"):
            db.session.add(
                Document(knowledge_base_id=base.id, title="Filter fixture", status=status)
            )
        for status in ("SUCCESS", "FAILED"):
            db.session.add(
                QALog(
                    knowledge_base_id=base.id,
                    request_id=f"filter_{status}",
                    source_type="web",
                    question="Filter fixture",
                    status=status,
                )
            )
        db.session.commit()
        base_id = str(base.id)
    return base_id


@pytest.mark.parametrize(
    "resource,statuses",
    [
        ("knowledge-bases", {"active", "disabled", "archived"}),
        ("knowledge-bases/{base_id}/documents", {"active", "archived"}),
        ("documents", {"active", "archived"}),
        ("users", {"active", "disabled"}),
        ("roles", {"active", "disabled"}),
        ("robots", {"active", "disabled"}),
        ("pages", {"active", "disabled"}),
        ("qa-logs", {"SUCCESS", "FAILED"}),
    ],
)
def test_status_filters_return_all_when_cleared_and_only_selected_when_set(
    client, status_records, resource, statuses
):
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Test-Password-2026!",
        },
    )
    headers = {"Authorization": f"Bearer {login.get_json()['data']['access_token']}"}
    path = f"/api/v1/{resource.format(base_id=status_records)}"

    # A cleared selector must behave like an omitted filter, including older clients
    # that have already serialized undefined/null into their query string.
    for empty in (None, "", "undefined", "null", " \t", " undefined "):
        params = {"q": "Filter fixture", "page_size": 100}
        if empty is not None:
            params["status"] = empty
        response = client.get(path, headers=headers, query_string=params)
        assert response.status_code == 200, (resource, empty, response.get_json())
        data = response.get_json()["data"]
        assert {item["status"] for item in data["items"]} == statuses, (resource, empty)
        assert data["total"] == len(statuses)

    for status in statuses:
        response = client.get(
            path,
            headers=headers,
            query_string={
                "q": "Filter fixture",
                "status": status,
            },
        )
        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["total"] == 1
        assert [item["status"] for item in data["items"]] == [status]

    # Clearing status must retain keyword and pagination constraints.
    for page in range(1, len(statuses) + 1):
        response = client.get(
            path,
            headers=headers,
            query_string={
                "q": "Filter fixture",
                "status": "undefined",
                "page_size": 1,
                "page": page,
            },
        )
        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["total"] == len(statuses)
        assert len(data["items"]) == 1
        assert data["page"] == page
    response = client.get(
        path,
        headers=headers,
        query_string={
            "q": "no matching fixture",
            "status": "undefined",
        },
    )
    assert response.get_json()["data"]["total"] == 0

    if resource in {"knowledge-bases", "knowledge-bases/{base_id}/documents", "users", "roles"}:
        assert (
            client.get(path, headers=headers, query_string={"status": "invalid"}).status_code == 422
        )
