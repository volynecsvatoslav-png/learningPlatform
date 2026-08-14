import hashlib
from unittest.mock import Mock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import User
from media_assets.models import MediaAsset
from media_assets.serializers import ProxyUploadSerializer
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery staple"


def owner(email: str, vendor: Vendor) -> User:
    user = User.objects.create_user(
        email, PASSWORD, is_staff=True, email_verified_at=timezone.now()
    )
    VendorMember.objects.create(vendor=vendor, user=user, role=VendorMember.Role.OWNER)
    return user


def request_data(vendor: Vendor) -> dict[str, object]:
    return {
        "vendor_id": str(vendor.id),
        "kind": "image",
        "original_name": "cover.png",
        "content_type": "image/png",
        "size_bytes": 4,
        "sha256": hashlib.sha256(b"test").hexdigest(),
    }


def test_upload_requires_session_authentication(client: Client) -> None:
    response = client.post(
        "/api/v1/backoffice/media/uploads", data={}, content_type="application/json"
    )

    assert response.status_code == 403


def test_upload_requires_csrf_for_an_authenticated_session() -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = owner("owner@example.com", vendor)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(
        "/api/v1/backoffice/media/uploads",
        data=request_data(vendor),
        content_type="application/json",
    )

    assert response.status_code == 403


def test_upload_creates_private_random_key_and_presigned_post(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = owner("owner@example.com", vendor)
    client.force_login(user)
    storage = Mock()
    storage.create_upload_post.return_value = {"url": "http://minio/upload", "fields": {"key": "x"}}

    with patch("media_assets.views.get_storage", return_value=storage):
        response = client.post(
            "/api/v1/backoffice/media/uploads",
            data=request_data(vendor),
            content_type="application/json",
        )

    assert response.status_code == 201
    asset = MediaAsset.objects.get()
    assert asset.object_key == f"vendors/{vendor.id}/assets/{asset.id}/source"
    assert asset.status == MediaAsset.Status.PENDING
    storage.create_upload_post.assert_called_once_with(
        key=asset.object_key,
        content_type="image/png",
        size_bytes=4,
        sha256=asset.sha256,
    )


def test_upload_for_foreign_vendor_returns_404(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    client.force_login(owner("alpha@example.com", alpha))

    response = client.post(
        "/api/v1/backoffice/media/uploads", data=request_data(beta), content_type="application/json"
    )

    assert response.status_code == 404


def test_foreign_asset_returns_404_and_anonymous_stream_is_rejected(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    alpha_owner = owner("alpha@example.com", alpha)
    beta_owner = owner("beta@example.com", beta)
    asset = MediaAsset.objects.create(
        vendor=beta,
        kind="image",
        bucket="bucket",
        object_key="vendors/beta/assets/x/source",
        original_name="cover.png",
        content_type="image/png",
        size_bytes=4,
        sha256=hashlib.sha256(b"test").hexdigest(),
        created_by=beta_owner,
        status=MediaAsset.Status.READY,
    )

    client.force_login(alpha_owner)
    assert client.get(f"/api/v1/backoffice/media/{asset.id}").status_code == 404
    client.logout()
    assert client.get(f"/api/v1/media/{asset.id}/stream-url").status_code == 403


@override_settings(MEDIA_TRANSFER_MODE="presigned")
def test_stream_url_is_no_store_and_never_exposes_object_key(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = owner("owner@example.com", vendor)
    asset = MediaAsset.objects.create(
        vendor=vendor,
        kind="image",
        bucket="bucket",
        object_key="vendors/alpha/assets/x/source",
        original_name="cover.png",
        content_type="image/png",
        size_bytes=4,
        sha256=hashlib.sha256(b"test").hexdigest(),
        created_by=user,
        status=MediaAsset.Status.READY,
    )
    client.force_login(user)
    storage = Mock()
    storage.create_download_url.return_value = "http://minio/signed"

    with patch("media_assets.views.get_storage", return_value=storage):
        response = client.get(f"/api/v1/media/{asset.id}/stream-url")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json() == {"url": "http://minio/signed"}


def test_proxy_stream_url_is_same_origin(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = owner("owner@example.com", vendor)
    asset = MediaAsset.objects.create(
        vendor=vendor,
        kind="image",
        bucket="bucket",
        object_key="private/random-key",
        original_name="cover.png",
        content_type="image/png",
        size_bytes=4,
        sha256=hashlib.sha256(b"test").hexdigest(),
        created_by=user,
        status=MediaAsset.Status.READY,
    )
    client.force_login(user)
    with patch("media_assets.views.get_storage"):
        response = client.get(f"/api/v1/media/{asset.id}/stream-url")
    assert response.status_code == 200
    assert response.json() == {"url": f"/api/v1/vendor/media/{asset.id}/content"}


def test_completion_queues_validation_once(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = owner("owner@example.com", vendor)
    asset = MediaAsset.objects.create(
        vendor=vendor,
        kind="image",
        bucket="bucket",
        object_key="vendors/alpha/assets/x/source",
        original_name="cover.png",
        content_type="image/png",
        size_bytes=4,
        sha256=hashlib.sha256(b"test").hexdigest(),
        created_by=user,
    )
    client.force_login(user)

    with patch("media_assets.views.validate_media_asset.delay") as delay:
        response = client.post(f"/api/v1/backoffice/media/{asset.id}/complete")

    assert response.status_code == 202
    asset.refresh_from_db()
    assert asset.status == MediaAsset.Status.UPLOADED
    delay.assert_called_once_with(str(asset.id))


def test_proxy_upload_streams_file_and_queues_validation(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = owner("owner@example.com", vendor)
    client.force_login(user)
    storage = Mock()
    payload = b"proxy-video-bytes"
    upload = SimpleUploadedFile("lesson.mp4", payload, content_type="video/mp4")
    with (
        patch("media_assets.views.get_storage", return_value=storage),
        patch("media_assets.views.validate_media_asset.delay") as delay,
    ):
        response = client.post(
            "/api/v1/vendor/media/upload-file",
            {"vendor_id": str(vendor.id), "kind": "video", "file": upload},
        )
    assert response.status_code == 201
    asset = MediaAsset.objects.get()
    assert asset.status == MediaAsset.Status.UPLOADED
    assert asset.original_name == "lesson.mp4"
    assert str(vendor.id) in asset.object_key
    assert "lesson.mp4" not in asset.object_key
    storage.upload_fileobj.assert_called_once()
    delay.assert_called_once_with(str(asset.id))

    editor = User.objects.create_user(
        "editor@example.com", PASSWORD, email_verified_at=timezone.now()
    )
    VendorMember.objects.create(vendor=vendor, user=editor, role=VendorMember.Role.EDITOR)
    client.force_login(editor)
    editor_upload = SimpleUploadedFile("editor.png", b"png", content_type="image/png")
    with (
        patch("media_assets.views.get_storage", return_value=storage),
        patch("media_assets.views.validate_media_asset.delay"),
    ):
        editor_response = client.post(
            "/api/v1/vendor/media/upload-file",
            {"vendor_id": str(vendor.id), "kind": "image", "file": editor_upload},
        )
    assert editor_response.status_code == 201


def test_proxy_upload_rejects_foreign_vendor_and_invalid_file(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    client.force_login(owner("alpha@example.com", alpha))
    foreign = SimpleUploadedFile("ok.mp4", b"x", content_type="video/mp4")
    assert (
        client.post(
            "/api/v1/vendor/media/upload-file",
            {"vendor_id": str(beta.id), "kind": "video", "file": foreign},
        ).status_code
        == 404
    )
    traversal = SimpleUploadedFile("evil.mp4", b"x", content_type="video/mp4")
    traversal._name = "../evil.mp4"
    serializer = ProxyUploadSerializer(
        data={"vendor_id": str(alpha.id), "kind": "video", "file": traversal}
    )
    assert not serializer.is_valid()
    assert "file" in serializer.errors
    bad_type = SimpleUploadedFile("photo.png", b"x", content_type="text/plain")
    assert (
        client.post(
            "/api/v1/vendor/media/upload-file",
            {"vendor_id": str(alpha.id), "kind": "image", "file": bad_type},
        ).status_code
        == 400
    )


@override_settings(MEDIA_TRANSFER_MODE="presigned")
def test_proxy_upload_is_disabled_in_presigned_mode(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    client.force_login(owner("owner@example.com", vendor))
    upload = SimpleUploadedFile("lesson.mp4", b"x", content_type="video/mp4")

    response = client.post(
        "/api/v1/vendor/media/upload-file",
        {"vendor_id": str(vendor.id), "kind": "video", "file": upload},
    )

    assert response.status_code == 404


def test_proxy_content_supports_range_and_is_private(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = owner("owner@example.com", vendor)
    asset = MediaAsset.objects.create(
        vendor=vendor,
        kind="video",
        bucket="bucket",
        object_key="private/random-key",
        original_name="lesson.mp4",
        content_type="video/mp4",
        size_bytes=10,
        sha256=hashlib.sha256(b"0123456789").hexdigest(),
        created_by=user,
        status=MediaAsset.Status.READY,
    )
    client.force_login(user)
    storage = Mock()
    storage.head.return_value = {"ContentLength": 10}
    storage.read_range.return_value = iter([b"234"])
    with patch("media_assets.views.get_storage", return_value=storage):
        response = client.get(f"/api/v1/vendor/media/{asset.id}/content", HTTP_RANGE="bytes=2-4")
    assert response.status_code == 206
    assert response["Content-Range"] == "bytes 2-4/10"
    assert response["Content-Length"] == "3"
    assert response["Accept-Ranges"] == "bytes"
    assert response["Cache-Control"] == "private, no-store"
    assert b"private/random-key" not in b"".join(response.streaming_content)

    with patch("media_assets.views.get_storage", return_value=storage):
        invalid = client.get(f"/api/v1/vendor/media/{asset.id}/content", HTTP_RANGE="bytes=99-100")
    assert invalid.status_code == 416
    assert invalid["Content-Range"] == "bytes */10"
