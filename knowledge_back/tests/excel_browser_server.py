"""Real Excel API for browser regression tests, with isolated DB and object storage."""

import importlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import app as app_fixture
from flask import Response, request
from test_excel import styled_xlsx
from werkzeug.serving import make_server

from app.excel_authoring import parse_workbook

with tempfile.TemporaryDirectory(prefix="kbs-excel-browser-") as directory:
    monkeypatch = pytest.MonkeyPatch()
    app = app_fixture.__wrapped__(Path(directory), monkeypatch)
    app.config.update(INDEX_WORKER_AUTOSTART=False)
    documents = importlib.import_module("app.documents")
    indexer = importlib.import_module("app.indexer")
    objects = {}

    def put(key, stream, *, bucket, length, content_type):
        payload = stream.read()
        assert len(payload) == length
        objects[key] = payload

    def schedule():
        while indexer.process_one(app):
            pass

    monkeypatch.setattr(documents, "put_object", put)
    monkeypatch.setattr(documents, "read_object", lambda key, **kw: objects[key])
    monkeypatch.setattr(documents, "stat_object", lambda key, **kw: SimpleNamespace(size=len(objects[key])))
    monkeypatch.setattr(documents, "delete_object", lambda key, **kw: objects.pop(key, None))
    monkeypatch.setattr(documents, "presign_put", lambda *a, **kw: "/fixture/requires-fallback")
    monkeypatch.setattr(documents, "_schedule_index_task", schedule)
    monkeypatch.setattr(indexer, "read_object", lambda key, **kw: objects[key])
    monkeypatch.setattr(indexer, "embed_texts", lambda texts: ([[1.0, 0.0] for _ in texts], "browser-test"))

    @app.get("/fixture/styled.xlsx")
    def fixture():
        return Response(styled_xlsx(), content_type=documents.CONTENT_TYPES[".xlsx"])

    @app.get("/fixture/objects/<path:key>")
    def download(key):
        return Response(objects[key], content_type=documents.CONTENT_TYPES[".xlsx"], headers={
            "Content-Disposition": 'attachment; filename="download.xlsx"',
        })

    @app.post("/fixture/inspect")
    def inspect_xlsx():
        return parse_workbook("download.xlsx", request.get_data())

    server = make_server("127.0.0.1", 0, app)
    origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(documents, "presign_get", lambda key, *a, **kw: f"{origin}/fixture/objects/{key}")
    print(json.dumps({"origin": origin}), flush=True)
    server.serve_forever()
