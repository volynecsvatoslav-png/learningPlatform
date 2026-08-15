import base64
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import boto3
from botocore.config import Config
from django.conf import settings


class ObjectStorage(Protocol):
    def create_upload_post(
        self,
        *,
        key: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]: ...

    def head(self, *, key: str) -> dict[str, Any]: ...

    def read(self, *, key: str) -> Iterator[bytes]: ...

    def read_range(self, *, key: str, start: int, end: int | None = None) -> Iterator[bytes]: ...

    def upload_fileobj(self, *, key: str, fileobj: Any, content_type: str) -> None: ...

    def create_download_url(self, *, key: str) -> str: ...

    def delete(self, *, key: str) -> None: ...


class S3Body(Protocol):
    def iter_chunks(self, chunk_size: int) -> Iterator[bytes]: ...


class S3Client(Protocol):
    def generate_presigned_post(self, **kwargs: Any) -> dict[str, Any]: ...

    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_object(self, **kwargs: Any) -> dict[str, S3Body]: ...

    def upload_fileobj(self, fileobj: Any, bucket: str, key: str, **kwargs: Any) -> None: ...

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str: ...

    def delete_object(self, **kwargs: Any) -> None: ...


def checksum_base64(sha256: str) -> str:
    return base64.b64encode(bytes.fromhex(sha256)).decode("ascii")


@dataclass(frozen=True, slots=True)
class S3ObjectStorage:
    bucket: str
    upload_ttl_seconds: int
    get_ttl_seconds: int
    checksum_policy_supported: bool
    client: S3Client
    presign_client: S3Client

    @classmethod
    def from_settings(cls) -> "S3ObjectStorage":
        client_options = {
            "region_name": settings.MEDIA_S3_REGION,
            "aws_access_key_id": settings.MEDIA_S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.MEDIA_S3_SECRET_ACCESS_KEY,
            "use_ssl": settings.MEDIA_S3_USE_SSL,
            "config": Config(s3={"addressing_style": "path"}),
        }
        client = boto3.client(
            "s3",
            endpoint_url=settings.MEDIA_S3_ENDPOINT_URL,
            **client_options,
        )
        return cls(
            bucket=settings.MEDIA_S3_BUCKET,
            upload_ttl_seconds=settings.MEDIA_UPLOAD_URL_TTL_SECONDS,
            get_ttl_seconds=settings.MEDIA_GET_URL_TTL_SECONDS,
            checksum_policy_supported=settings.MEDIA_S3_CHECKSUM_POLICY_SUPPORTED,
            client=client,
            presign_client=boto3.client(
                "s3", endpoint_url=settings.MEDIA_S3_PUBLIC_ENDPOINT_URL, **client_options
            ),
        )

    def create_upload_post(
        self,
        *,
        key: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        fields: dict[str, str] = {
            "Content-Type": content_type,
            "x-amz-server-side-encryption": "AES256",
        }
        conditions: list[Any] = [
            {"key": key},
            {"Content-Type": content_type},
            {"x-amz-server-side-encryption": "AES256"},
            ["content-length-range", size_bytes, size_bytes],
        ]
        if self.checksum_policy_supported:
            checksum = checksum_base64(sha256)
            fields["x-amz-checksum-sha256"] = checksum
            conditions.append({"x-amz-checksum-sha256": checksum})
        return self.presign_client.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=self.upload_ttl_seconds,
        )

    def head(self, *, key: str) -> dict[str, Any]:
        return self.client.head_object(Bucket=self.bucket, Key=key)

    def read(self, *, key: str) -> Iterator[bytes]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        yield from body.iter_chunks(chunk_size=1024 * 1024)

    def read_range(self, *, key: str, start: int, end: int | None = None) -> Iterator[bytes]:
        body = self.client.get_object(
            Bucket=self.bucket,
            Key=key,
            Range=f"bytes={start}-{'' if end is None else end}",
        )["Body"]
        yield from body.iter_chunks(chunk_size=1024 * 1024)

    def upload_fileobj(self, *, key: str, fileobj: Any, content_type: str) -> None:
        self.client.upload_fileobj(
            fileobj,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type, "ServerSideEncryption": "AES256"},
        )

    def create_download_url(self, *, key: str) -> str:
        return self.presign_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseCacheControl": "no-store",
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=self.get_ttl_seconds,
            HttpMethod="GET",
        )

    def delete(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def get_storage() -> ObjectStorage:
    return S3ObjectStorage.from_settings()
