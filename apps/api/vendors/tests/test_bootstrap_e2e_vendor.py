from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from accounts.models import User
from learning.models import ContentUnit, Course, Lesson, Module
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db

PASSWORD = "unusual e2e vendor b password 73918"
ENVIRONMENT = {
    "E2E_BOOTSTRAP_ENABLED": "true",
    "E2E_VENDOR_B_NAME": "E2E Vendor B",
    "E2E_VENDOR_B_SLUG": "e2e-vendor-b",
    "E2E_VENDOR_B_OWNER_EMAIL": "owner-b@example.com",
    "E2E_VENDOR_B_OWNER_PASSWORD": PASSWORD,
    "E2E_VENDOR_B_COURSE_TITLE": "E2E Course B",
    "E2E_VENDOR_B_COURSE_SLUG": "e2e-course-b",
}


@pytest.fixture(autouse=True)
def enable_debug(settings: object) -> None:
    settings.DEBUG = True  # type: ignore[attr-defined]


def configure_environment(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in {**ENVIRONMENT, **overrides}.items():
        monkeypatch.setenv(name, value)


def run_command() -> str:
    output = StringIO()
    call_command("bootstrap_e2e_vendor", stdout=output)
    return output.getvalue()


def test_requires_debug_and_explicit_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch, E2E_BOOTSTRAP_ENABLED="false")
    with pytest.raises(CommandError, match="requires DEBUG"):
        run_command()

    configure_environment(monkeypatch)
    with override_settings(DEBUG=False), pytest.raises(CommandError, match="requires DEBUG"):
        run_command()

    assert not Vendor.objects.exists()
    assert not Course.objects.exists()


def test_requires_all_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch, E2E_VENDOR_B_COURSE_SLUG="")

    with pytest.raises(CommandError, match="E2E_VENDOR_B_COURSE_SLUG"):
        run_command()

    assert not Vendor.objects.exists()


def test_creates_vendor_b_owner_and_published_course(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch)

    output = run_command()

    vendor = Vendor.objects.get(slug="e2e-vendor-b")
    owner = User.objects.get(email="owner-b@example.com")
    assert vendor.status == Vendor.Status.ACTIVE
    assert VendorMember.objects.get(vendor=vendor, user=owner).role == VendorMember.Role.OWNER
    assert owner.check_password(PASSWORD)
    assert owner.email_verified_at is not None
    assert not owner.is_staff and not owner.is_superuser

    course = Course.objects.get(vendor=vendor, slug="e2e-course-b")
    assert course.status == Course.Status.PUBLISHED
    assert course.current_revision is not None
    lesson = Lesson.objects.get(module__course=course, is_published=True)
    assert ContentUnit.objects.get(lesson=lesson, type=ContentUnit.Type.TEXT)
    assert Module.objects.get(course=course)

    assert not User.objects.filter(email__startswith="learner").exists()
    assert "bootstrap complete" in output
    assert PASSWORD not in output
    assert "E2E_VENDOR_B_ACCESS_LINK" not in output


def test_is_idempotent_without_printing_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch)
    first = run_command()
    ids = (
        Vendor.objects.get().id,
        User.objects.count(),
        Course.objects.get().id,
    )

    second = run_command()

    assert (
        Vendor.objects.get().id,
        User.objects.count(),
        Course.objects.get().id,
    ) == ids
    assert "already exists" in second
    assert PASSWORD not in first
    assert PASSWORD not in second


def test_rejects_password_mismatch_without_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch)
    run_command()
    password_hash = User.objects.get(email="owner-b@example.com").password

    configure_environment(monkeypatch, E2E_VENDOR_B_OWNER_PASSWORD="different unusual pass 99124")
    with pytest.raises(CommandError, match="password does not match") as caught:
        run_command()

    assert User.objects.get(email="owner-b@example.com").password == password_hash
    assert "different unusual pass 99124" not in str(caught.value)
    assert User.objects.count() == 1


def test_password_is_never_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_environment(monkeypatch, E2E_VENDOR_B_OWNER_PASSWORD="short")
    with pytest.raises(CommandError, match="E2E_VENDOR_B_OWNER_PASSWORD is invalid") as caught:
        run_command()
    assert "short" not in str(caught.value)
