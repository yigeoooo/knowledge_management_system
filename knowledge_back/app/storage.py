"""Private MinIO object storage adapter used by document management."""

from datetime import timedelta
from urllib.parse import urlparse
from uuid import UUID

from flask import current_app
from minio import Minio
from minio.error import S3Error
from minio.helpers import ObjectWriteResult


class StorageError(RuntimeError):
    """An object storage operation failed or storage is not configured."""


def _endpoint(value: str) -> tuple[str, bool]:
    value = value.strip()
    if not value:
        raise StorageError("MinIO 服务地址未配置")
    if "://" in value:
        parsed = urlparse(value)
        if not parsed.hostname:
            raise StorageError("MinIO 服务地址不正确")
        return parsed.netloc, parsed.scheme == "https"
    return value, False


def _client(*, public: bool = False) -> Minio:
    configured = "MINIO_PUBLIC_ENDPOINT" if public else "MINIO_ENDPOINT"
    endpoint, endpoint_secure = _endpoint(current_app.config[configured])
    access_key = current_app.config["MINIO_ACCESS_KEY"]
    secret_key = current_app.config["MINIO_SECRET_KEY"]
    if not access_key or not secret_key:
        raise StorageError("MinIO 访问凭据未配置")
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=endpoint_secure or current_app.config["MINIO_SECURE"],
    )


def bucket_name() -> str:
    value = current_app.config["MINIO_BUCKET"].strip()
    if not value:
        raise StorageError("MinIO Bucket 未配置")
    return value


def knowledge_base_bucket(knowledge_base_id: UUID | str) -> str:
    """Return the stable MinIO bucket assigned to one knowledge base.

    Bucket names are derived from the UUID rather than the editable knowledge
    base code.  This keeps existing objects addressable when an administrator
    renames a code and also satisfies MinIO's bucket naming rules.
    """

    try:
        value = UUID(str(knowledge_base_id)).hex
    except (TypeError, ValueError, AttributeError) as error:
        raise StorageError("知识库 ID 不正确，无法准备对象存储") from error
    return f"knowledge-base-{value}"


def ensure_bucket(bucket: str | None = None) -> str:
    client = _client()
    name = (bucket or bucket_name()).strip()
    if not name:
        raise StorageError("MinIO Bucket 未配置")
    try:
        if not client.bucket_exists(name):
            client.make_bucket(name)
    except S3Error as error:
        if error.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise StorageError("无法准备 MinIO 存储桶") from error
    except Exception as error:
        raise StorageError("无法连接 MinIO 或准备存储桶") from error
    return name


def presign_put(object_key: str, *, bucket: str | None = None) -> str:
    target_bucket = ensure_bucket(bucket)
    try:
        return _client(public=True).presigned_put_object(
            target_bucket, object_key, expires=timedelta(seconds=current_app.config["MINIO_URL_SECONDS"])
        )
    except Exception as error:
        raise StorageError("无法生成 MinIO 上传地址") from error


def presign_get(object_key: str, filename: str, *, bucket: str | None = None, inline: bool = False, content_type: str | None = None) -> str:
    target_bucket = ensure_bucket(bucket)
    try:
        return _client(public=True).presigned_get_object(
            target_bucket,
            object_key,
            expires=timedelta(seconds=current_app.config["MINIO_URL_SECONDS"]),
            response_headers={
                "response-content-disposition": (
                    f'inline; filename="{filename}"' if inline else f'attachment; filename="{filename}"'
                ),
                "response-content-type": content_type or "application/octet-stream",
            },
        )
    except Exception as error:
        raise StorageError("无法生成 MinIO 下载地址") from error


def stat_object(object_key: str, *, bucket: str | None = None):
    try:
        return _client().stat_object(bucket or bucket_name(), object_key)
    except Exception as error:
        raise StorageError("MinIO 中找不到该文件") from error


def read_object(object_key: str, *, bucket: str | None = None, max_size: int) -> bytes:
    response = None
    try:
        response = _client().get_object(bucket or bucket_name(), object_key)
        data = response.read(max_size + 1)
        if len(data) > max_size:
            raise StorageError("文件超过允许读取大小")
        return data
    except StorageError:
        raise
    except Exception as error:
        raise StorageError("无法读取 MinIO 文件") from error
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def put_object(object_key: str, data, *, bucket: str | None = None, length: int, content_type: str) -> ObjectWriteResult:
    target_bucket = ensure_bucket(bucket)
    try:
        return _client().put_object(
            target_bucket, object_key, data, length=length, content_type=content_type
        )
    except Exception as error:
        raise StorageError("无法写入 MinIO 文件") from error


def delete_object(object_key: str, *, bucket: str | None = None) -> None:
    try:
        _client().remove_object(bucket or bucket_name(), object_key)
    except Exception as error:
        raise StorageError("无法删除 MinIO 文件") from error
