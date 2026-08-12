import hashlib
from unittest.mock import Mock

from media_assets.storage import S3ObjectStorage, checksum_base64


def test_presigned_post_enforces_exact_key_type_size_and_checksum() -> None:
    client = Mock()
    client.generate_presigned_post.return_value = {"url": "http://minio"}
    storage = S3ObjectStorage(
        bucket="media",
        upload_ttl_seconds=600,
        get_ttl_seconds=60,
        checksum_policy_supported=True,
        client=client,
        presign_client=client,
    )
    digest = hashlib.sha256(b"test").hexdigest()

    storage.create_upload_post(
        key="vendors/x/assets/y/source", content_type="image/png", size_bytes=4, sha256=digest
    )

    kwargs = client.generate_presigned_post.call_args.kwargs
    assert kwargs["Bucket"] == "media"
    assert kwargs["Key"] == "vendors/x/assets/y/source"
    assert kwargs["ExpiresIn"] == 600
    assert ["content-length-range", 4, 4] in kwargs["Conditions"]
    assert {"x-amz-checksum-sha256": checksum_base64(digest)} in kwargs["Conditions"]


def test_presigned_get_is_short_lived_and_disables_caching() -> None:
    client = Mock()
    storage = S3ObjectStorage(
        bucket="media",
        upload_ttl_seconds=600,
        get_ttl_seconds=60,
        checksum_policy_supported=False,
        client=client,
        presign_client=client,
    )

    storage.create_download_url(key="vendors/x/assets/y/source")

    kwargs = client.generate_presigned_url.call_args.kwargs
    assert kwargs["ExpiresIn"] == 60
    assert kwargs["Params"]["ResponseCacheControl"] == "no-store"
