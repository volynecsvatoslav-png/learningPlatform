import pytest
from django.contrib.auth import authenticate
from django.test import Client
from django.utils import timezone

from accounts.models import User
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery staple"


def make_vendor_admin(*, verified: bool = True) -> User:
    user = User.objects.create_user(
        "owner@example.com",
        PASSWORD,
        is_staff=True,
        email_verified_at=timezone.now() if verified else None,
    )
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    VendorMember.objects.create(vendor=vendor, user=user, role=VendorMember.Role.OWNER)
    return user


def test_verified_vendor_admin_can_log_in_case_insensitively(client: Client) -> None:
    user = make_vendor_admin()

    assert authenticate(username="OWNER@EXAMPLE.COM", password=PASSWORD) == user
    response = client.post(
        "/backoffice/login/",
        {"username": "OWNER@EXAMPLE.COM", "password": PASSWORD},
        follow=True,
    )

    assert response.status_code == 200
    assert response.wsgi_request.user == user
    user.refresh_from_db()
    assert user.last_login_at is not None


def test_unverified_vendor_admin_cannot_log_in(client: Client) -> None:
    make_vendor_admin(verified=False)

    response = client.post(
        "/backoffice/login/", {"username": "owner@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert "sessionid" not in client.cookies


def test_invalid_backoffice_login_returns_form_without_server_error(client: Client) -> None:
    response = client.post(
        "/backoffice/login/", {"username": "missing@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated
