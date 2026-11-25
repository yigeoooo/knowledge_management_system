"""Expiring browser file links served through the API's existing public origin."""

from pathlib import PurePath
from urllib.parse import quote

from flask import Response, current_app, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ...core.http import ApiError
from ...integrations.storage.minio_adapter import bucket_name, open_object, stat_object
from .service import CONTENT_TYPES, _api_storage


def _signer():
    return URLSafeTimedSerializer(
        current_app.config["JWT_SECRET_KEY"], salt="document-browser-file-v1"
    )


def presign_browser_get(object_key, filename, *, bucket=None, inline=False, content_type=None):
    """Only authorized callers mint links; iframes cannot send bearer headers.

    Keep these links separate from MinIO's public URLs used by external AI services.
    A relative API path works with both Vite's dev proxy and deployed reverse proxies.
    MIME types are resolved from supported extensions when serving, not upload metadata.
    """
    token = _signer().dumps({
        "bucket": bucket or bucket_name(), "key": object_key,
        "filename": filename, "inline": inline,
    })
    return url_for("documents.document_file", token=token)


def serve_browser_file(token):
    try:
        grant = _signer().loads(token, max_age=current_app.config["MINIO_URL_SECONDS"])
    except BadSignature:
        raise ApiError("文件链接无效或已过期，请重新打开预览或下载", 403, 40301) from None

    key, bucket = grant["key"], grant["bucket"]
    info = _api_storage(stat_object, key, bucket=bucket)
    size = int(info.size)
    start, end, status = 0, size, 200
    # A full response is always valid when If-Range cannot be verified.
    if request.method == "GET" and request.headers.get("Range") and not request.headers.get("If-Range"):
        requested = request.range
        bounds = requested.range_for_length(size) if requested else None
        if bounds is None:
            return Response(status=416, headers={"Content-Range": f"bytes */{size}"})
        start, end = bounds
        status = 206

    filename = grant["filename"]
    extension = PurePath(filename).suffix.lower()
    disposition = "inline" if grant["inline"] else "attachment"
    fallback_extension = extension if extension in CONTENT_TYPES else ""
    headers = {
        "Content-Type": CONTENT_TYPES.get(extension, "application/octet-stream"),
        "Content-Length": str(end - start),
        "Accept-Ranges": "bytes",
        "Content-Disposition": (
            f'{disposition}; filename="document{fallback_extension}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        ),
        "Referrer-Policy": "no-referrer",
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end - 1}/{size}"
    if extension == ".svg":
        # Uploaded SVGs must not execute scripts on the application's origin.
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    if request.method == "HEAD" or size == 0:
        return Response(status=status, headers=headers)

    upstream = _api_storage(open_object, key, bucket=bucket, offset=start, length=end - start)
    closed = False

    def close():
        nonlocal closed
        if not closed:
            closed = True
            try:
                upstream.close()
            finally:
                upstream.release_conn()

    def chunks():
        try:
            yield from upstream.stream(64 * 1024)
        finally:
            close()

    response = Response(chunks(), status=status, headers=headers)
    response.call_on_close(close)
    return response
