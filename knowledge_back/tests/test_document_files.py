"""Browser file links must work when MinIO is reachable only by the API server."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from itsdangerous import TimestampSigner

from app.extensions import db
from app.integrations.storage import minio_adapter as storage
from app.models import Document, DocumentVersion, KnowledgeBase


@pytest.fixture
def pdf_file(app, client, monkeypatch):
    payload = b"%PDF-1.7\nprivate PDF fixture\n%%EOF"
    streams = []

    def get_object(bucket, key, *, offset=0, length=0):
        assert (bucket, key) == ("private-bucket", "private/document.pdf")
        stream = BytesIO(payload[offset:offset + length] if length else payload[offset:])
        response = SimpleNamespace(
            stream=lambda size: iter(lambda: stream.read(size), b""),
            close=Mock(side_effect=stream.close),
            release_conn=Mock(),
        )
        streams.append(response)
        return response

    minio = SimpleNamespace(
        bucket_exists=lambda bucket: True,
        presigned_get_object=lambda *a, **kw: "http://127.0.0.1:9000/private/document.pdf",
        stat_object=Mock(return_value=SimpleNamespace(size=len(payload))),
        get_object=Mock(side_effect=get_object),
    )
    monkeypatch.setattr(storage, "_client", lambda **kw: minio)
    app.config.update(MINIO_ENDPOINT="127.0.0.1:9000", MINIO_PUBLIC_ENDPOINT="127.0.0.1:9000")
    with app.app_context():
        base = db.session.scalar(db.select(KnowledgeBase))
        document = Document(knowledge_base_id=base.id, title="课程介绍", status="active")
        db.session.add(document)
        db.session.flush()
        version = DocumentVersion(
            document_id=document.id, version_no=1, filename="课程介绍.pdf",
            minio_bucket="private-bucket", minio_object_key="private/document.pdf",
            content_type="application/pdf", file_size=len(payload), status="INDEXED",
        )
        db.session.add(version)
        db.session.flush()
        document.current_version_id = version.id
        document_id = str(document.id)
        db.session.commit()
    login = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "Test-Password-2026!",
    })
    headers = {"Authorization": f"Bearer {login.json['data']['access_token']}"}
    return SimpleNamespace(
        payload=payload, streams=streams, minio=minio,
        document_id=document_id, headers=headers,
    )


def file_link(client, fixture, kind="preview"):
    response = client.get(
        f"/api/v1/documents/{fixture.document_id}/{kind}-url", headers=fixture.headers,
    )
    assert response.status_code == 200
    return response.json["data"][f"{kind}_url"]


@pytest.mark.parametrize("kind,disposition", [("preview", "inline"), ("download", "attachment")])
def test_private_minio_files_are_served_from_site_origin(client, pdf_file, kind, disposition):
    url = file_link(client, pdf_file, kind)
    assert not urlsplit(url).netloc, "Browser file URLs must not expose the internal MinIO host"
    assert url.startswith("/api/v1/")
    # An iframe/download cannot attach the application's Authorization header.
    response = client.get(url)
    assert response.status_code == 200
    assert response.data == pdf_file.payload
    assert response.content_type == "application/pdf"
    assert response.headers["Content-Disposition"].startswith(disposition + ";")
    assert "filename*=UTF-8''" in response.headers["Content-Disposition"]
    assert response.headers["Content-Length"] == str(len(pdf_file.payload))
    assert response.headers["Accept-Ranges"] == "bytes"
    response.close()
    pdf_file.streams[0].close.assert_called_once()
    pdf_file.streams[0].release_conn.assert_called_once()


@pytest.mark.parametrize("header,start,end", [("bytes=0-7", 0, 8), ("bytes=9-", 9, None), ("bytes=-5", -5, None)])
def test_pdf_byte_ranges(client, pdf_file, header, start, end):
    response = client.get(file_link(client, pdf_file), headers={"Range": header})
    assert response.status_code == 206
    assert response.data == pdf_file.payload[start:end]
    assert response.headers["Content-Length"] == str(len(response.data))
    start = start if start >= 0 else len(pdf_file.payload) + start
    end = end or len(pdf_file.payload)
    assert response.headers["Content-Range"] == f"bytes {start}-{end - 1}/{len(pdf_file.payload)}"
    response.close()


def test_head_and_unsatisfiable_ranges_do_not_open_object_stream(client, pdf_file):
    url = file_link(client, pdf_file)
    response = client.head(url)
    assert response.status_code == 200 and not response.data
    assert response.headers["Content-Length"] == str(len(pdf_file.payload))
    response = client.get(url, headers={"Range": "bytes=9999-"})
    assert response.status_code == 416
    assert response.headers["Content-Range"] == f"bytes */{len(pdf_file.payload)}"
    pdf_file.minio.get_object.assert_not_called()


def test_file_links_require_permission_and_valid_unexpired_signature(app, client, pdf_file, monkeypatch):
    assert client.get(f"/api/v1/documents/{pdf_file.document_id}/preview-url").status_code == 401
    url = file_link(client, pdf_file)
    assert client.get(urlsplit(url).path).status_code == 403
    assert client.get(url + "tampered").status_code == 403
    timestamp = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: timestamp(self) + app.config["MINIO_URL_SECONDS"] + 1)
    assert client.get(url).status_code == 403
    pdf_file.minio.stat_object.assert_not_called()
    pdf_file.minio.get_object.assert_not_called()


def test_browser_disconnect_releases_minio_connection(client, pdf_file):
    response = client.get(file_link(client, pdf_file), buffered=False)
    response.close()
    pdf_file.streams[0].close.assert_called_once()
    pdf_file.streams[0].release_conn.assert_called_once()


def test_minio_read_failure_returns_service_error(client, pdf_file):
    pdf_file.minio.get_object.side_effect = OSError("storage unavailable")
    response = client.get(file_link(client, pdf_file))
    assert response.status_code == 503
    assert response.json["message"] == "无法读取 MinIO 文件"


def test_inline_svg_is_sandboxed_even_if_stored_with_an_unsafe_mime(app, client, pdf_file):
    with app.app_context():
        version = db.session.scalar(db.select(DocumentVersion))
        version.filename = "绘图.svg"
        version.content_type = "text/html"
        db.session.commit()
    response = client.get(file_link(client, pdf_file))
    assert response.content_type == "image/svg+xml"
    assert "sandbox" in response.headers["Content-Security-Policy"]
    response.close()


def test_evaluation_pdf_preview_uses_the_same_site_file_endpoint(app, client, pdf_file):
    from app.application.documents.preview import preview_version

    with app.test_request_context():
        version = db.session.scalar(db.select(DocumentVersion))
        preview = preview_version(version)
    assert preview["kind"] == "pdf"
    assert not urlsplit(preview["url"]).netloc
    response = client.get(preview["url"])
    assert response.status_code == 200 and response.data == pdf_file.payload
    response.close()
