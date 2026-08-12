from unittest.mock import patch

import pytest
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import User
from learner.models import AccessLink, Enrollment, hash_access_token
from learning.models import Course
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery staple"


def member(email: str, vendor: Vendor, role: str) -> User:
    user = User.objects.create_user(
        email,
        PASSWORD,
        is_staff=True,
        email_verified_at=timezone.now(),
    )
    VendorMember.objects.create(vendor=vendor, user=user, role=role)
    return user


def course(vendor: Vendor, slug: str = "course") -> Course:
    return Course.objects.create(
        vendor=vendor,
        title="Course",
        slug=slug,
        short_description="Short",
    )


def json_post(client: Client, path: str, data: dict[str, object]):
    return client.post(path, data=data, content_type="application/json")


def test_vendor_login_is_session_based_and_rate_limited(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    member("owner@example.com", vendor, VendorMember.Role.OWNER)

    response = json_post(
        client,
        "/api/v1/vendor/auth/login",
        {"email": "OWNER@example.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert "sessionid" in client.cookies
    assert client.get("/api/v1/vendor/me").status_code == 200


@override_settings(VENDOR_AUTH_RATE_LIMIT=1)
def test_vendor_login_rate_limit_is_neutral(client: Client) -> None:
    client.defaults["REMOTE_ADDR"] = "192.0.2.10"
    response = json_post(
        client,
        "/api/v1/vendor/auth/login",
        {"email": "missing@example.com", "password": PASSWORD},
    )
    assert response.status_code == 401

    response = json_post(
        client,
        "/api/v1/vendor/auth/login",
        {"email": "another@example.com", "password": PASSWORD},
    )
    assert response.status_code == 429
    assert response.json() == {"code": "AUTH_RATE_LIMITED"}


def test_backoffice_is_superuser_only(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    owner = member("owner@example.com", vendor, VendorMember.Role.OWNER)
    client.force_login(owner)

    assert client.get("/backoffice/").status_code == 302

    admin = User.objects.create_superuser("admin@example.com", PASSWORD)
    client.force_login(admin)
    assert client.get("/backoffice/").status_code == 200


def test_vendor_course_and_structure_are_tenant_scoped(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    owner = member("owner@example.com", alpha, VendorMember.Role.OWNER)
    foreign_course = course(beta)
    client.force_login(owner)

    assert client.get(f"/api/v1/vendor/courses?vendor_id={alpha.id}").json() == []
    assert client.get(f"/api/v1/vendor/courses/{foreign_course.id}").status_code == 404

    response = json_post(
        client,
        f"/api/v1/vendor/courses?vendor_id={alpha.id}",
        {"title": "Alpha Course", "slug": "alpha-course"},
    )
    assert response.status_code == 201
    created = response.json()

    response = json_post(
        client,
        f"/api/v1/vendor/courses/{created['id']}/structure",
        {
            "entity": "module",
            "action": "create",
            "title": "Module",
            "position": 1,
        },
    )
    assert response.status_code == 201
    module_id = response.json()["id"]
    response = json_post(
        client,
        f"/api/v1/vendor/courses/{created['id']}/structure",
        {
            "entity": "lesson",
            "action": "create",
            "parent_id": module_id,
            "title": "Lesson",
            "position": 1,
            "is_published": True,
        },
    )
    assert response.status_code == 201
    lesson_id = response.json()["id"]
    response = json_post(
        client,
        f"/api/v1/vendor/courses/{created['id']}/structure",
        {
            "entity": "content",
            "action": "create",
            "parent_id": lesson_id,
            "type": "text",
            "text_markdown": "# Hello",
            "position": 1,
        },
    )
    assert response.status_code == 201

    response = client.post(f"/api/v1/vendor/courses/{created['id']}/publish")
    assert response.status_code == 200
    assert response.json()["revision"] == 1


def test_editor_cannot_manage_access(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    editor = member("editor@example.com", vendor, VendorMember.Role.EDITOR)
    client.force_login(editor)

    assert client.get(f"/api/v1/vendor/access?vendor_id={vendor.id}").status_code == 404
    response = json_post(
        client,
        "/api/v1/vendor/access/grant",
        {"vendor_id": str(vendor.id), "learner_email": "learner@example.com", "course_ids": []},
    )
    assert response.status_code == 400


def test_grant_revoke_and_reissue_access_store_only_hash(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    owner = member("owner@example.com", vendor, VendorMember.Role.OWNER)
    published = course(vendor)
    published.status = Course.Status.PUBLISHED
    published.save(update_fields=("status",))
    client.force_login(owner)

    with patch("vendor_api.views.secrets.token_urlsafe", side_effect=["a" * 43, "b" * 43]):
        response = json_post(
            client,
            "/api/v1/vendor/access/grant",
            {
                "vendor_id": str(vendor.id),
                "learner_email": "learner@example.com",
                "course_ids": [str(published.id)],
            },
        )
        assert response.status_code == 201
        enrollment_id = response.json()[0]["id"]
        first = AccessLink.objects.get()
        assert first.token_hash == hash_access_token("a" * 43)
        assert "a" * 43 not in first.token_hash
        assert len(mail.outbox) == 1

        response = client.post(f"/api/v1/vendor/access/{enrollment_id}/reissue")
        assert response.status_code == 200
        assert AccessLink.objects.filter(revoked_at__isnull=True).count() == 1
        assert AccessLink.objects.filter(token_hash=first.token_hash).exists()

    response = client.post(f"/api/v1/vendor/access/{enrollment_id}/revoke")
    assert response.status_code == 200
    assert Enrollment.objects.get(pk=enrollment_id).status == Enrollment.Status.REVOKED
