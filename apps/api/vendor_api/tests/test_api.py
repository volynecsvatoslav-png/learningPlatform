from unittest.mock import patch

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from learner.models import AccessLink, Enrollment, hash_access_token
from learning.models import ContentUnit, Course, Lesson, Module
from media_assets.models import MediaAsset
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


def asset(
    vendor: Vendor,
    created_by: User,
    *,
    kind: str = MediaAsset.Kind.IMAGE,
    status: str = MediaAsset.Status.READY,
    name: str = "cover.png",
) -> MediaAsset:
    return MediaAsset.objects.create(
        vendor=vendor,
        kind=kind,
        status=status,
        bucket="private",
        object_key=f"vendors/{vendor.id}/{name}",
        original_name=name,
        content_type="image/png" if kind == MediaAsset.Kind.IMAGE else "audio/mpeg",
        size_bytes=4,
        sha256="0" * 64,
        created_by=created_by,
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


def test_course_create_and_patch_reject_foreign_cover_asset(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    owner = member("owner@example.com", alpha, VendorMember.Role.OWNER)
    foreign_owner = member("other@example.com", beta, VendorMember.Role.OWNER)
    foreign_asset = asset(beta, foreign_owner)
    client.force_login(owner)

    response = json_post(
        client,
        f"/api/v1/vendor/courses?vendor_id={alpha.id}",
        {"title": "Unsafe", "slug": "unsafe", "cover_asset_id": str(foreign_asset.id)},
    )
    assert response.status_code == 409
    assert response.json() == {"code": "MEDIA_NOT_READY"}
    assert not Course.objects.filter(vendor=alpha, slug="unsafe").exists()

    own_course = course(alpha)
    response = client.patch(
        f"/api/v1/vendor/courses/{own_course.id}",
        data={"cover_asset_id": str(foreign_asset.id)},
        content_type="application/json",
    )
    assert response.status_code == 409
    own_course.refresh_from_db()
    assert own_course.cover_asset_id is None


def test_course_cover_must_be_ready_image(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    owner = member("owner@example.com", vendor, VendorMember.Role.OWNER)
    pending = asset(vendor, owner, status=MediaAsset.Status.PENDING, name="pending.png")
    audio = asset(vendor, owner, kind=MediaAsset.Kind.AUDIO, name="track.mp3")
    ready = asset(vendor, owner, name="ready.png")
    client.force_login(owner)

    for invalid in (pending, audio):
        response = json_post(
            client,
            f"/api/v1/vendor/courses?vendor_id={vendor.id}",
            {
                "title": f"Course {invalid.id}",
                "slug": f"course-{invalid.id}",
                "cover_asset_id": str(invalid.id),
            },
        )
        assert response.status_code == 409

    response = json_post(
        client,
        f"/api/v1/vendor/courses?vendor_id={vendor.id}",
        {"title": "Ready", "slug": "ready", "cover_asset_id": str(ready.id)},
    )
    assert response.status_code == 201
    assert response.json()["cover_asset_id"] == str(ready.id)


def test_content_units_require_matching_ready_media_and_can_change_type(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    owner = member("owner@example.com", vendor, VendorMember.Role.OWNER)
    draft = course(vendor)
    module = Module.objects.create(course=draft, title="Module", position=1)
    lesson = Lesson.objects.create(module=module, title="Lesson", position=1)
    image = asset(vendor, owner)
    audio = asset(vendor, owner, kind=MediaAsset.Kind.AUDIO, name="track.mp3")
    client.force_login(owner)
    path = f"/api/v1/vendor/courses/{draft.id}/structure"

    response = json_post(
        client,
        path,
        {
            "entity": "content",
            "action": "create",
            "parent_id": str(lesson.id),
            "type": "image",
            "media_asset_id": str(audio.id),
        },
    )
    assert response.status_code == 409

    response = json_post(
        client,
        path,
        {
            "entity": "content",
            "action": "create",
            "parent_id": str(lesson.id),
            "type": "image",
            "media_asset_id": str(image.id),
        },
    )
    assert response.status_code == 201
    unit_id = response.json()["id"]

    response = json_post(
        client,
        path,
        {
            "entity": "content",
            "action": "update",
            "id": unit_id,
            "type": "text",
            "text_markdown": "# Replaced with text",
        },
    )
    assert response.status_code == 200
    unit = ContentUnit.objects.get(pk=unit_id)
    assert unit.type == ContentUnit.Type.TEXT
    assert unit.media_asset_id is None
    assert unit.text_markdown == "# Replaced with text"


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


def test_existing_user_cannot_be_taken_over_when_adding_member(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    owner = member("owner@example.com", alpha, VendorMember.Role.OWNER)
    existing = member("existing@example.com", beta, VendorMember.Role.EDITOR)
    old_password = existing.password
    client.force_login(owner)

    response = json_post(
        client,
        "/api/v1/vendor/members",
        {
            "vendor_id": str(alpha.id),
            "email": existing.email,
            "role": VendorMember.Role.EDITOR,
            "password": "new malicious password value",
        },
    )
    assert response.status_code == 409
    assert response.json() == {"code": "MEMBER_EMAIL_CONFLICT"}
    existing.refresh_from_db()
    assert existing.password == old_password
    assert existing.check_password(PASSWORD)
    assert not existing.check_password("new malicious password value")
    assert not VendorMember.objects.filter(vendor=alpha, user=existing).exists()


def test_superuser_cannot_be_taken_over_when_adding_member(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    owner = member("owner@example.com", vendor, VendorMember.Role.OWNER)
    admin = User.objects.create_superuser("admin@example.com", PASSWORD)
    old_password = admin.password
    client.force_login(owner)

    response = json_post(
        client,
        "/api/v1/vendor/members",
        {
            "vendor_id": str(vendor.id),
            "email": admin.email,
            "role": VendorMember.Role.EDITOR,
            "password": "new malicious password value",
        },
    )
    assert response.status_code == 409
    admin.refresh_from_db()
    assert admin.password == old_password
    assert admin.is_superuser


def test_owner_can_create_new_editor_and_list_members(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    owner = member("owner@example.com", vendor, VendorMember.Role.OWNER)
    client.force_login(owner)

    response = json_post(
        client,
        "/api/v1/vendor/members",
        {
            "vendor_id": str(vendor.id),
            "email": "editor@example.com",
            "role": VendorMember.Role.EDITOR,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    created = User.objects.get(email="editor@example.com")
    assert created.check_password(PASSWORD)
    assert not created.is_staff
    assert client.get(f"/api/v1/vendor/members?vendor_id={vendor.id}").status_code == 200


def test_vendor_password_reset_uses_django_password_validation(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = member("owner@example.com", vendor, VendorMember.Role.OWNER)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    response = json_post(
        client,
        f"/api/v1/vendor/auth/password-reset/{uid}/{token}",
        {"password": "short"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "PASSWORD_INVALID"
    user.refresh_from_db()
    assert user.check_password(PASSWORD)

    response = json_post(
        client,
        f"/api/v1/vendor/auth/password-reset/{uid}/{token}",
        {"password": "a sufficiently strong replacement password"},
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password("a sufficiently strong replacement password")


def test_vendor_media_list_is_tenant_scoped_and_hides_storage_keys(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    owner = member("owner@example.com", alpha, VendorMember.Role.OWNER)
    other = member("other@example.com", beta, VendorMember.Role.OWNER)
    own_asset = asset(alpha, owner)
    asset(beta, other, name="foreign.png")
    client.force_login(owner)

    response = client.get(f"/api/v1/vendor/media?vendor_id={alpha.id}")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [str(own_asset.id)]
    assert "object_key" not in response.json()[0]
    assert "bucket" not in response.json()[0]
    assert client.get(f"/api/v1/vendor/media?vendor_id={beta.id}").status_code == 404


def test_learner_session_cannot_authorize_vendor_api(client: Client) -> None:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = member("shared@example.com", vendor, VendorMember.Role.OWNER)
    published = course(vendor)
    published.status = Course.Status.PUBLISHED
    published.save(update_fields=("status",))
    enrollment = Enrollment.objects.create(learner=user, course=published)
    token = "a" * 43
    AccessLink.objects.create(enrollment=enrollment, token_hash=hash_access_token(token))

    response = json_post(client, "/api/v1/learner/session", {"token": token})
    assert response.status_code == 200
    assert client.get("/api/v1/learner/courses").status_code == 200
    assert client.get("/api/v1/vendor/me").status_code in {401, 403}
