"""Read-only previews using the same Word and Excel parsers as document management."""

from pathlib import PurePath

from ...core.http import ApiError
from ...integrations.storage.minio_adapter import presign_get, read_object
from .service import (
    CONTENT_TYPES,
    EXCEL_EXTENSIONS,
    TEXT_EXTENSIONS,
    _api_storage,
    _max_document_size,
)


def preview_version(version):
    extension = PurePath(version.filename).suffix.lower()
    if extension in TEXT_EXTENSIONS | EXCEL_EXTENSIONS | {".docx"}:
        content = _api_storage(
            read_object,
            version.minio_object_key,
            bucket=version.minio_bucket,
            max_size=_max_document_size(),
        )
        try:
            if extension in EXCEL_EXTENSIONS:
                from ...excel_authoring import parse_workbook

                return {"kind": "excel", "workbook": parse_workbook(version.filename, content)}
            if extension == ".docx":
                from ...docx_preview import docx_html

                return {"kind": "word", "html": docx_html(content)}
            return {
                "kind": "text" if extension == ".txt" else "markdown",
                "content": content.decode("utf-8-sig"),
            }
        except (RuntimeError, ValueError, TypeError) as error:
            raise ApiError("文档预览解析失败，请下载原文件查看", 422) from error
    kind = "download"
    if extension == ".pdf":
        kind = "pdf"
    elif extension in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        kind = "image"
    elif extension in {".mp4", ".webm", ".mov"}:
        kind = "video"
    url = _api_storage(
        presign_get,
        version.minio_object_key,
        version.filename,
        bucket=version.minio_bucket,
        inline=kind != "download",
        content_type=CONTENT_TYPES.get(extension),
    )
    return {"kind": kind, "url": url}
