import hashlib
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from accounts.models import User
from media_assets.models import MediaAsset
from media_assets.tasks import validate_media_asset
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db


def uploaded_asset(kind: str = MediaAsset.Kind.VIDEO) -> MediaAsset:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = User.objects.create_user(
        "owner@example.com",
        "correct horse battery staple",
        is_staff=True,
        email_verified_at=timezone.now(),
    )
    VendorMember.objects.create(vendor=vendor, user=user, role=VendorMember.Role.OWNER)
    return MediaAsset.objects.create(
        vendor=vendor,
        kind=kind,
        status=MediaAsset.Status.UPLOADED,
        bucket="bucket",
        object_key="vendors/alpha/assets/x/source",
        original_name="lesson.mp4",
        content_type="video/mp4",
        size_bytes=4,
        sha256=hashlib.sha256(b"test").hexdigest(),
        created_by=user,
    )


def test_worker_marks_validated_asset_ready() -> None:
    asset = uploaded_asset()
    storage = Mock()
    source = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    asset.sha256 = hashlib.sha256(source).hexdigest()
    asset.size_bytes = len(source)
    asset.save(update_fields=("sha256", "size_bytes"))
    storage.head.return_value = {"ContentLength": len(source)}
    storage.read.return_value = iter((source,))
    probe = {
        "format": {"duration": "1.500"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }

    with (
        patch("media_assets.tasks.get_storage", return_value=storage),
        patch("media_assets.validation._ffprobe", return_value=probe),
    ):
        validate_media_asset(str(asset.id))

    asset.refresh_from_db()
    assert asset.status == MediaAsset.Status.READY
    assert asset.duration_seconds == Decimal("1.500")
    assert asset.width == 1920
    assert asset.height == 1080


def test_worker_rejects_invalid_asset_and_attempts_private_cleanup() -> None:
    asset = uploaded_asset()
    storage = Mock()
    storage.head.return_value = {"ContentLength": asset.size_bytes}
    storage.read.return_value = iter((b"not media",))

    with patch("media_assets.tasks.get_storage", return_value=storage):
        validate_media_asset(str(asset.id))

    asset.refresh_from_db()
    assert asset.status == MediaAsset.Status.REJECTED
    assert asset.rejection_reason == "File content does not match the declared media type."
    storage.delete.assert_called_once_with(key=asset.object_key)
