import re

import pytest
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import User
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db
OLD_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "new correct horse battery staple"


def make_owner() -> User:
    user = User.objects.create_user(
        "owner@example.com",
        OLD_PASSWORD,
        is_staff=True,
        email_verified_at=timezone.now(),
    )
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    VendorMember.objects.create(vendor=vendor, user=user, role=VendorMember.Role.OWNER)
    return user


def test_anonymous_user_can_open_password_reset_pages(client: Client) -> None:
    reset = client.get("/backoffice/password_reset/")
    done = client.get("/backoffice/password_reset/done/")
    complete = client.get("/backoffice/password_reset/complete/")

    assert reset.status_code == done.status_code == complete.status_code == 200


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_response_is_existence_neutral(client: Client) -> None:
    make_owner()

    existing = client.post("/backoffice/password_reset/", {"email": "owner@example.com"})
    missing = client.post("/backoffice/password_reset/", {"email": "missing@example.com"})

    assert existing.status_code == missing.status_code == 302
    assert existing.url == missing.url == "/backoffice/password_reset/done/"
    assert len(mail.outbox) == 1


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_token_is_single_use(client: Client) -> None:
    user = make_owner()
    client.post("/backoffice/password_reset/", {"email": user.email})
    reset_url = re.search(r"http://testserver(/backoffice/password_reset/\S+)", mail.outbox[0].body)
    assert reset_url is not None

    initial = client.get(reset_url.group(1))
    assert initial.status_code == 302
    set_password_url = initial.url
    changed = client.post(
        set_password_url,
        {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
    )
    assert changed.status_code == 302
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)

    reused = client.get(reset_url.group(1), follow=True)
    assert reused.status_code == 200
    assert reused.context["validlink"] is False
