import pytest
from django.http import HttpRequest
from django.utils import timezone

from accounts.admin import backoffice_site
from accounts.models import User
from media_assets.admin import MediaAssetAdmin
from media_assets.models import MediaAsset
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db


def test_vendor_member_can_open_empty_media_section() -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    editor = User.objects.create_user(
        "editor@example.com",
        "correct horse battery staple",
        is_staff=True,
        email_verified_at=timezone.now(),
    )
    VendorMember.objects.create(vendor=vendor, user=editor, role=VendorMember.Role.EDITOR)
    request = HttpRequest()
    request.user = editor
    admin = MediaAssetAdmin(MediaAsset, backoffice_site)

    assert admin.has_module_permission(request)
    assert admin.has_view_permission(request)
    assert not admin.get_queryset(request).exists()
