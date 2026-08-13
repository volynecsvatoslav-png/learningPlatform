from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from accounts.models import User
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db

PASSWORD = "unusual e2e password 48371"
ENVIRONMENT = {
    "E2E_BOOTSTRAP_ENABLED": "true",
    "E2E_OWNER_EMAIL": "owner.e2e@example.com",
    "E2E_OWNER_PASSWORD": PASSWORD,
    "E2E_VENDOR_NAME": "E2E Vendor",
    "E2E_VENDOR_SLUG": "e2e-vendor",
}


@pytest.fixture(autouse=True)
def enable_debug(settings: object) -> None:
    settings.DEBUG = True  # type: ignore[attr-defined]


def configure_environment(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in {**ENVIRONMENT, **overrides}.items():
        monkeypatch.setenv(name, value)


def run_command() -> str:
    output = StringIO()
    call_command("bootstrap_e2e_owner", stdout=output)
    return output.getvalue()


def test_requires_debug_and_explicit_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch, E2E_BOOTSTRAP_ENABLED="false")
    with pytest.raises(CommandError, match="requires DEBUG"):
        run_command()

    configure_environment(monkeypatch)
    with override_settings(DEBUG=False), pytest.raises(CommandError, match="requires DEBUG"):
        run_command()

    assert not User.objects.exists()
    assert not Vendor.objects.exists()


def test_requires_all_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch, E2E_VENDOR_SLUG="")

    with pytest.raises(CommandError, match="E2E_VENDOR_SLUG"):
        run_command()

    assert not User.objects.exists()
    assert not Vendor.objects.exists()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"E2E_OWNER_EMAIL": "not-an-email"}, "E2E_OWNER_EMAIL is invalid"),
        ({"E2E_VENDOR_SLUG": "not a slug"}, "E2E_VENDOR_SLUG is invalid"),
        ({"E2E_OWNER_PASSWORD": "short"}, "E2E_OWNER_PASSWORD is invalid"),
    ],
)
def test_validates_requested_values_without_leaking_password(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str], message: str
) -> None:
    configure_environment(monkeypatch, **overrides)

    with pytest.raises(CommandError, match=message) as caught:
        run_command()

    assert overrides.get("E2E_OWNER_PASSWORD", PASSWORD) not in str(caught.value)
    assert not User.objects.exists()
    assert not Vendor.objects.exists()


def test_creates_exact_least_privilege_owner_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch)

    output = run_command()

    vendor = Vendor.objects.get()
    user = User.objects.get()
    membership = VendorMember.objects.get()
    assert vendor.name == "E2E Vendor"
    assert vendor.slug == "e2e-vendor"
    assert vendor.status == Vendor.Status.ACTIVE
    assert user.email == "owner.e2e@example.com"
    assert user.check_password(PASSWORD)
    assert user.email_verified_at is not None
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser
    assert not user.groups.exists()
    assert not user.user_permissions.exists()
    assert membership.vendor == vendor
    assert membership.user == user
    assert membership.role == VendorMember.Role.OWNER
    assert "created" in output
    assert PASSWORD not in output


def test_is_idempotent_for_only_the_exact_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch)
    run_command()
    ids = (User.objects.get().id, Vendor.objects.get().id, VendorMember.objects.get().id)

    output = run_command()

    assert (User.objects.get().id, Vendor.objects.get().id, VendorMember.objects.get().id) == ids
    assert "already exists" in output
    assert PASSWORD not in output


def test_rejects_nonempty_database_without_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch)
    existing = User.objects.create_user(
        "someone-else@example.com",
        "another unusual password 92846",
        email_verified_at=timezone.now(),
    )

    with pytest.raises(CommandError, match="exact requested tuple") as caught:
        run_command()

    assert list(User.objects.values_list("id", flat=True)) == [existing.id]
    assert not Vendor.objects.exists()
    assert not VendorMember.objects.exists()
    assert PASSWORD not in str(caught.value)


def test_rejects_password_mismatch_for_existing_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch)
    run_command()
    password_hash = User.objects.get().password
    monkeypatch.setenv("E2E_OWNER_PASSWORD", "different unusual password 73519")

    with pytest.raises(CommandError, match="exact requested tuple") as caught:
        run_command()

    assert User.objects.get().password == password_hash
    assert User.objects.count() == Vendor.objects.count() == VendorMember.objects.count() == 1
    assert "different unusual password 73519" not in str(caught.value)
