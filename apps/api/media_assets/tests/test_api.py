import hashlib
from unittest.mock import Mock, patch

import pytest
from django.test import Client
from django.utils import timezone

from accounts.models import User
from media_assets.models import MediaAsset
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
