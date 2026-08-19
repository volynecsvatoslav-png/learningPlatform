import hashlib
import json
import secrets
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
import pytest
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from accounts.models import User
from config.offline_keys import DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK
from learner.models import (
    AccessPass,
    Device,
    Enrollment,
    LearnerSession,
    LessonProgress,
    OfflineLicense,
    RecoveryChallenge,
    hash_access_token,
)
from learner.tests.helpers import activate, make_device, request_exchange
from learning.models import ContentUnit, Course, Lesson, Module
from learning.services import publish_course
from media_assets.models import MediaAsset
from vendors.models import Vendor

pytestmark = pytest.mark.django_db


def make_access() -> tuple[User, Course, Lesson, str]:
    learner = User.objects.create_user("learner@example.com")
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    course = Course.objects.create(vendor=vendor, title="Published", slug="published")
    module = Module.objects.create(course=course, title="Module", position=1)
    lesson = Lesson.objects.create(module=module, title="Lesson", position=1, is_published=True)
    ContentUnit.objects.create(
        lesson=lesson,
        type=ContentUnit.Type.TEXT,
        position=1,
        text_markdown="# Hello",
    )
    course.status = Course.Status.PUBLISHED
    publish_course(course)
    token = secrets.token_urlsafe(32)
    Enrollment.objects.create(user=learner, vendor=vendor, course=course)
    AccessPass.objects.create(
        user=learner,
        vendor=vendor,
        token_hash=hash_access_token(token),
        token_prefix=token[:12],
    )
    return learner, course, lesson, token


def test_access_token_is_hashed_and_exchange_creates_server_session(client: Client) -> None:
    learner, course, _, token = make_access()

    assert AccessPass.objects.get().token_hash != token
    activate(client, token)
    session = LearnerSession.objects.get()
    assert session.learner == learner
    assert session.access_pass is not None
    assert session.device is not None
    assert session.revoked_at is None
    assert client.get("/api/v1/learner/courses").status_code == 200
    course_response = client.get(f"/api/v1/learner/courses/{course.id}")
    assert course_response.status_code == 200
    assert course_response.json()["viewer"] == {
        "email": learner.email,
        "session_id": str(session.id)[:8],
    }


def test_learner_session_uses_dedicated_expiry(client: Client, settings) -> None:  # type: ignore[no-untyped-def]
    settings.LEARNER_SESSION_AGE = 45 * 24 * 60 * 60
    _, _, _, token = make_access()
    activate(client, token)
    learner_session = LearnerSession.objects.get()
    django_session = Session.objects.get(session_key=learner_session.session_key)
    remaining = (django_session.expire_date - timezone.now()).total_seconds()
    assert settings.LEARNER_SESSION_AGE - 5 <= remaining <= settings.LEARNER_SESSION_AGE


def test_new_device_transfer_requires_confirmation_and_replaces_old(client: Client) -> None:
    _, _, _, token = make_access()
    first = Client()
    second = Client()
    first_device = make_device()
    activate(first, token, device=first_device)
    old_session = LearnerSession.objects.get()
    old_device = Device.objects.get()

    response = request_exchange(second, token, device=make_device())
    assert response.status_code == 409
    assert response.json()["code"] == "DEVICE_TRANSFER_CONFIRMATION_REQUIRED"

    old_session.refresh_from_db()
    assert old_session.revoked_at is None
    assert first.get("/api/v1/learner/courses").status_code == 200

    activate(second, token, device=make_device(), confirm_transfer=True)
    access_pass = AccessPass.objects.get()
    assert access_pass.generation == 2
    old_session.refresh_from_db()
    old_device.refresh_from_db()
    assert old_session.revoked_at is not None
    assert old_session.revoke_reason == LearnerSession.RevokeReason.REPLACED
    assert old_device.revoked_at is not None

    response = first.get("/api/v1/learner/courses")
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_REPLACED"
    assert second.get("/api/v1/learner/courses").status_code == 200


def test_used_or_tampered_challenge_is_rejected(client: Client) -> None:
    _, _, _, token = make_access()
    installation_id, public_key_jwk, sign = make_device()
    assert (
        request_exchange(client, token, device=(installation_id, public_key_jwk, sign)).status_code
        == 200
    )

    replay = client.post(
        "/api/v1/auth/access/exchange",
        data={
            "token": token,
            "installation_id": str(installation_id),
            "public_key_jwk": public_key_jwk,
            "challenge": "x" * 43,
            "signature": "y" * 43,
        },
        content_type="application/json",
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "DEVICE_PROOF_INVALID"


def test_same_installation_id_with_same_key_reauthenticates_without_confirmation(
    client: Client,
) -> None:
    _, _, _, token = make_access()
    device = make_device()
    activate(client, token, device=device)
    assert request_exchange(client, token, device=device).status_code == 200
    assert LearnerSession.objects.filter(revoked_at__isnull=True).count() == 1


def test_same_installation_id_with_different_key_requires_transfer(client: Client) -> None:
    _, _, _, token = make_access()
    first_device = make_device()
    activate(client, token, device=first_device)
    old_device = Device.objects.get()
    new_key_device = make_device()
    same_id_new_key = (first_device[0], new_key_device[1], new_key_device[2])

    inspect = client.post(
        "/api/v1/auth/access/inspect",
        data={
            "token": token,
            "installation_id": str(first_device[0]),
            "public_key_jwk": new_key_device[1],
        },
        content_type="application/json",
    )
    assert inspect.status_code == 200
    assert inspect.json()["device_match"] is False
    assert inspect.json()["transfer_required"] is True

    response = request_exchange(client, token, device=same_id_new_key)
    assert response.status_code == 409
    assert response.json()["code"] == "DEVICE_TRANSFER_CONFIRMATION_REQUIRED"
    assert Device.objects.get(pk=old_device.pk).revoked_at is None

    confirmed = request_exchange(client, token, device=same_id_new_key, confirm_transfer=True)
    assert confirmed.status_code == 200
    access_pass = AccessPass.objects.get()
    assert access_pass.generation == 2
    old_device.refresh_from_db()
    assert old_device.revoked_at is not None
    activated = Device.objects.get(revoked_at__isnull=True)
    assert activated.id != old_device.id
    assert activated.installation_id == first_device[0]
    assert activated.public_key_fingerprint != old_device.public_key_fingerprint


def test_reauthentication_as_transfer_does_not_reuse_a_stale_key(client: Client) -> None:
    _, _, _, token = make_access()
    first_device = make_device()
    activate(client, token, device=first_device)

    second_device = make_device()
    activate(client, token, device=second_device, confirm_transfer=True)

    stale_key_attempt = request_exchange(client, token, device=first_device)
    assert stale_key_attempt.status_code == 409
    assert stale_key_attempt.json()["code"] == "DEVICE_TRANSFER_CONFIRMATION_REQUIRED"


@pytest.mark.django_db(transaction=True)
def test_exchange_and_recovery_work_without_ambient_transaction(client: Client) -> None:
    cache.clear()
    learner, _, _, token = make_access()
    activate(client, token)
    assert client.get("/api/v1/learner/courses").status_code == 200

    captured: dict[str, str] = {}

    def fake_send_mail(
        subject: str, message: str, from_email: str, recipient_list: list[str]
    ) -> None:
        captured["message"] = message

    with patch("learner.services.send_mail", side_effect=fake_send_mail):
        response = client.post(
            "/api/v1/auth/recovery/request",
            data={"email": learner.email},
            content_type="application/json",
        )
    assert response.status_code == 200
    recovery_token = captured["message"].split("#recovery=", 1)[1].strip()
    installation_id, public_key_jwk, sign = make_device()
    signed_message = (
        f"lms-recovery:{installation_id}:{hashlib.sha256(recovery_token.encode()).hexdigest()}"
    ).encode()
    exchange = client.post(
        "/api/v1/auth/recovery/exchange",
        data={
            "recovery_token": recovery_token,
            "installation_id": str(installation_id),
            "public_key_jwk": public_key_jwk,
            "signature": sign(signed_message),
        },
        content_type="application/json",
    )
    assert exchange.status_code == 200


def test_wrong_curve_jwk_is_rejected(client: Client) -> None:
    _, _, _, token = make_access()
    response = client.post(
        "/api/v1/auth/access/inspect",
        data={
            "token": token,
            "installation_id": str(uuid.uuid4()),
            "public_key_jwk": {"kty": "EC", "crv": "P-384", "x": "x" * 48, "y": "y" * 48},
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_auth_endpoints_are_rate_limited_per_ip(client: Client, settings) -> None:  # type: ignore[no-untyped-def]
    cache.clear()
    settings.ACCESS_AUTH_RATE_LIMIT = 2
    _, _, _, token = make_access()
    installation_id, public_key_jwk, _ = make_device()
    payload = {
        "token": token,
        "installation_id": str(installation_id),
        "public_key_jwk": public_key_jwk,
    }
    for _ in range(2):
        response = client.post(
            "/api/v1/auth/access/inspect",
            data=payload,
            content_type="application/json",
            REMOTE_ADDR="203.0.113.50",
        )
        assert response.status_code == 200
    limited = client.post(
        "/api/v1/auth/access/inspect",
        data=payload,
        content_type="application/json",
        REMOTE_ADDR="203.0.113.50",
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert (
        client.post(
            "/api/v1/auth/access/inspect",
            data=payload,
            content_type="application/json",
            REMOTE_ADDR="203.0.113.51",
        ).status_code
        == 200
    )


def test_me_heartbeat_and_logout(client: Client) -> None:
    _, course, _, token = make_access()
    installation_id, _, _ = activate(client, token)
    vendor = course.vendor

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json() == {
        "email": "learner@example.com",
        "vendor_id": str(vendor.id),
        "vendor_name": vendor.name,
        "device_id": str(Device.objects.get().id),
        "installation_id": str(installation_id),
        "generation": 1,
    }

    heartbeat = client.post("/api/v1/auth/heartbeat")
    assert heartbeat.status_code == 200
    assert heartbeat.json()["generation"] == 1
    assert heartbeat.json()["expires_at"] is not None

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    session = LearnerSession.objects.get()
    assert session.revoked_at is not None
    assert session.revoke_reason == LearnerSession.RevokeReason.LOGOUT
    assert client.get("/api/v1/learner/courses").status_code == 401


def test_heartbeat_rate_limited(client: Client, settings) -> None:  # type: ignore[no-untyped-def]
    cache.clear()
    settings.HEARTBEAT_RATE_LIMIT = 1
    settings.HEARTBEAT_RATE_WINDOW_SECONDS = 5
    _, _, _, token = make_access()
    activate(client, token)
    assert client.post("/api/v1/auth/heartbeat").status_code == 200
    assert client.post("/api/v1/auth/heartbeat").status_code == 429


def test_media_url_rate_limited_per_session(client: Client, settings) -> None:  # type: ignore[no-untyped-def]
    cache.clear()
    settings.MEDIA_URL_RATE_LIMIT = 1
    settings.MEDIA_URL_RATE_WINDOW_SECONDS = 60
    learner = User.objects.create_user("learner@example.com")
    creator = User.objects.create_user("creator@example.com")
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    course = Course.objects.create(vendor=vendor, title="Published", slug="published")
    module = Module.objects.create(course=course, title="Module", position=1)
    lesson = Lesson.objects.create(module=module, title="Lesson", position=1, is_published=True)
    asset = MediaAsset.objects.create(
        vendor=vendor,
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.READY,
        object_key="cover.png",
        original_name="cover.png",
        content_type="image/png",
        size_bytes=4,
        sha256="0" * 64,
        created_by=creator,
    )
    ContentUnit.objects.create(
        lesson=lesson,
        type=ContentUnit.Type.IMAGE,
        position=1,
        media_asset=asset,
    )
    course.status = Course.Status.PUBLISHED
    publish_course(course)
    token = secrets.token_urlsafe(32)
    Enrollment.objects.create(user=learner, vendor=vendor, course=course)
    AccessPass.objects.create(
        user=learner,
        vendor=vendor,
        token_hash=hash_access_token(token),
        token_prefix=token[:12],
    )
    activate(client, token)
    path = f"/api/v1/learner/courses/{course.id}/media/{asset.id}/stream-url"
    assert client.get(path).status_code == 200
    assert client.get(path).status_code == 429


def test_revoked_enrollment_blocks_course(client: Client) -> None:
    _, course, _, token = make_access()
    activate(client, token)
    enrollment = Enrollment.objects.get(course=course)
    enrollment.status = Enrollment.Status.REVOKED
    enrollment.revoked_at = timezone.now()
    enrollment.save(update_fields=("status", "revoked_at"))

    assert client.get(f"/api/v1/learner/courses/{course.id}").status_code == 404
    assert client.get("/api/v1/learner/courses").json() == []
    session = LearnerSession.objects.get()
    assert session.revoked_at is None


def test_progress_requires_owned_published_lesson_and_persists_completion(client: Client) -> None:
    _, course, lesson, token = make_access()
    activate(client, token)

    response = client.post(
        f"/api/v1/learner/courses/{course.id}/progress/{lesson.id}",
        data={"percent": 100, "status": "completed"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert LessonProgress.objects.get().status == "completed"
    assert client.get(f"/api/v1/learner/courses/{course.id}/progress").json()[0]["percent"] == 100

    response = client.post(
        f"/api/v1/learner/courses/{course.id}/progress/{lesson.id}",
        data={"percent": 1, "status": "in_progress"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["percent"] == 100
    assert response.json()["status"] == "completed"


def test_progress_payload_is_validated(client: Client) -> None:
    _, course, lesson, token = make_access()
    activate(client, token)

    response = client.post(
        f"/api/v1/learner/courses/{course.id}/progress/{lesson.id}",
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400
    response = client.post(
        f"/api/v1/learner/courses/{course.id}/progress/{lesson.id}",
        data={"percent": 10, "status": "completed"},
        content_type="application/json",
    )
    assert response.status_code == 400


def test_course_list_uses_published_snapshot_metadata(client: Client) -> None:
    _, course, _, token = make_access()
    published_title = course.title
    course.title = "Unpublished draft title"
    course.save(update_fields=("title",))
    activate(client, token)

    response = client.get("/api/v1/learner/courses")
    assert response.status_code == 200
    assert response.json()[0]["title"] == published_title


def test_foreign_course_and_media_url_are_not_available(client: Client) -> None:
    _, _, _, token = make_access()
    activate(client, token)
    foreign = Course.objects.create(
        vendor=Vendor.objects.create(name="Other", slug="other"),
        title="Other",
        slug="other-course",
    )
    assert client.get(f"/api/v1/learner/courses/{foreign.id}").status_code == 404
    assert (
        client.get(
            f"/api/v1/learner/courses/{foreign.id}/media/{foreign.id}/stream-url"
        ).status_code
        == 404
    )


def test_enrollment_for_other_vendor_is_invisible(client: Client) -> None:
    learner, course, _, token = make_access()
    other_vendor = Vendor.objects.create(name="Other", slug="other")
    other_course = Course.objects.create(vendor=other_vendor, title="Other", slug="other-course")
    other_module = Module.objects.create(course=other_course, title="Module", position=1)
    other_lesson = Lesson.objects.create(
        module=other_module, title="Lesson", position=1, is_published=True
    )
    ContentUnit.objects.create(
        lesson=other_lesson,
        type=ContentUnit.Type.TEXT,
        position=1,
        text_markdown="# Other",
    )
    other_course.status = Course.Status.PUBLISHED
    publish_course(other_course)
    Enrollment.objects.create(user=learner, vendor=other_vendor, course=other_course)
    activate(client, token)

    response = client.get("/api/v1/learner/courses")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(course.id)]
    assert client.get(f"/api/v1/learner/courses/{other_course.id}").status_code == 404


def test_recovery_rotates_pass_and_moves_to_new_device(client: Client) -> None:
    learner, _, _, token = make_access()
    first = Client()
    activate(first, token)
    old_pass = AccessPass.objects.get()
    old_device = Device.objects.get()
    old_session = LearnerSession.objects.get()

    captured: dict[str, str] = {}

    def fake_send_mail(
        subject: str, message: str, from_email: str, recipient_list: list[str]
    ) -> None:
        captured["message"] = message

    with patch("learner.services.send_mail", side_effect=fake_send_mail):
        response = client.post(
            "/api/v1/auth/recovery/request",
            data={"email": learner.email},
            content_type="application/json",
        )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    recovery_token = captured["message"].split("#recovery=", 1)[1].strip()
    assert RecoveryChallenge.objects.get().token_hash != recovery_token

    installation_id, public_key_jwk, sign = make_device()
    signed_message = (
        f"lms-recovery:{installation_id}:{hashlib.sha256(recovery_token.encode()).hexdigest()}"
    ).encode()
    exchange = client.post(
        "/api/v1/auth/recovery/exchange",
        data={
            "recovery_token": recovery_token,
            "installation_id": str(installation_id),
            "public_key_jwk": public_key_jwk,
            "signature": sign(signed_message),
        },
        content_type="application/json",
    )
    assert exchange.status_code == 200
    body = exchange.json()
    assert body["generation"] == 1
    assert body["access_link"].endswith(f"/app/#access={body['access_token']}")

    old_pass.refresh_from_db()
    old_device.refresh_from_db()
    old_session.refresh_from_db()
    assert old_pass.status == AccessPass.Status.REVOKED
    assert old_device.revoked_at is not None
    assert old_session.revoked_at is not None
    assert old_session.revoke_reason == LearnerSession.RevokeReason.REPLACED
    assert first.get("/api/v1/learner/courses").status_code == 401

    assert AccessPass.objects.filter(status=AccessPass.Status.ACTIVE).count() == 1
    assert (
        request_exchange(Client(), body["access_token"], confirm_transfer=True).status_code == 200
    )


def test_recovery_is_idempotent_and_rate_limited(client: Client, settings) -> None:  # type: ignore[no-untyped-def]
    cache.clear()
    settings.RECOVERY_REQUEST_EMAIL_LIMIT = 1
    learner, _, _, _ = make_access()
    with patch("learner.services.send_mail"):
        first = client.post(
            "/api/v1/auth/recovery/request",
            data={"email": learner.email},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.60",
        )
        second = client.post(
            "/api/v1/auth/recovery/request",
            data={"email": learner.email},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.60",
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["message"] == "Если доступ существует, письмо отправлено."
    assert RecoveryChallenge.objects.count() == 1

    with patch("learner.services.send_mail"):
        unknown = client.post(
            "/api/v1/auth/recovery/request",
            data={"email": "nobody@example.com"},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.61",
        )
    assert unknown.status_code == 200
    assert unknown.json()["message"] == "Если доступ существует, письмо отправлено."


def test_learner_media_url_is_no_store_and_object_key_is_not_returned(client: Client) -> None:
    _, course, lesson, token = make_access()
    asset = MediaAsset.objects.create(
        vendor=course.vendor,
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.READY,
        bucket="bucket",
        object_key="private/source",
        original_name="cover.png",
        content_type="image/png",
        size_bytes=4,
        sha256="0" * 64,
        created_by=User.objects.first(),
    )
    course.cover_asset = asset
    course.save(update_fields=("cover_asset",))
    lesson.content_units.all().delete()
    ContentUnit.objects.create(
        lesson=lesson,
        type=ContentUnit.Type.IMAGE,
        position=1,
        media_asset=asset,
    )
    course.status = Course.Status.PUBLISHED
    publish_course(course)
    activate(client, token)
    storage = Mock()
    storage.create_download_url.return_value = "http://signed.local/object"
    with patch("learner.views.get_storage", return_value=storage):
        response = client.get(f"/api/v1/learner/courses/{course.id}/media/{asset.id}/stream-url")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert "object_key" not in response.content.decode()


def test_learner_proxy_content_is_enrollment_scoped_and_supports_range(client: Client) -> None:
    learner, course, lesson, token = make_access()
    asset = MediaAsset.objects.create(
        vendor=course.vendor,
        kind=MediaAsset.Kind.VIDEO,
        status=MediaAsset.Status.READY,
        bucket="bucket",
        object_key="private/learner-video",
        original_name="lesson.mp4",
        content_type="video/mp4",
        size_bytes=10,
        sha256="0" * 64,
        created_by=learner,
    )
    lesson.content_units.all().delete()
    ContentUnit.objects.create(
        lesson=lesson, type=ContentUnit.Type.VIDEO, position=1, media_asset=asset
    )
    course.status = Course.Status.PUBLISHED
    publish_course(course)
    content_url = f"/api/v1/learner/courses/{course.id}/media/{asset.id}/content"
    stream_url = f"/api/v1/learner/courses/{course.id}/media/{asset.id}/stream-url"
    assert client.get(content_url).status_code == 401
    activate(client, token)
    stream_response = client.get(stream_url)
    assert stream_response.status_code == 200
    assert stream_response.json() == {"url": content_url}
    assert "private/learner-video" not in stream_response.content.decode()
    storage = Mock()
    storage.head.return_value = {"ContentLength": 10}
    storage.read_range.return_value = iter([b"234"])
    with patch("media_assets.views.get_storage", return_value=storage):
        response = client.get(
            content_url,
            HTTP_RANGE="bytes=2-4",
        )
    assert response.status_code == 206
    assert response["Content-Range"] == "bytes 2-4/10"
    assert response["Content-Disposition"] == "inline"
    assert response["Cache-Control"] == "private, no-store"
    assert response["Accept-Ranges"] == "bytes"
    assert b"private/learner-video" not in b"".join(response.streaming_content)

    enrollment = Enrollment.objects.get(course=course, user=learner)
    enrollment.status = Enrollment.Status.REVOKED
    enrollment.revoked_at = timezone.now()
    enrollment.save(update_fields=("status", "revoked_at"))
    assert client.get(content_url).status_code == 404


def test_offline_manifest_license_revision_and_revocation(client: Client) -> None:
    learner, course, lesson, token = make_access()
    asset = MediaAsset.objects.create(
        vendor=course.vendor,
        kind=MediaAsset.Kind.VIDEO,
        status=MediaAsset.Status.READY,
        bucket="private-bucket",
        object_key="private/offline-video",
        original_name="offline.mp4",
        content_type="video/mp4",
        size_bytes=10,
        sha256="1" * 64,
        created_by=learner,
    )
    lesson.content_units.all().delete()
    unit = ContentUnit.objects.create(
        lesson=lesson,
        type=ContentUnit.Type.VIDEO,
        position=1,
        media_asset=asset,
        is_downloadable=True,
    )
    allowed_revision = publish_course(course)
    manifest_url = f"/api/v1/learner/courses/{course.id}/offline-manifest"
    license_url = f"/api/v1/learner/courses/{course.id}/offline-license"
    media_url = (
        f"/api/v1/learner/courses/{course.id}/offline-media/{allowed_revision.id}/{asset.id}"
    )

    assert client.get(manifest_url).status_code == 401
    activate(client, token)
    manifest = client.get(manifest_url)
    assert manifest.status_code == 200
    assert manifest["Cache-Control"] == "private, no-store"
    assert manifest.json()["revision_id"] == str(allowed_revision.id)
    assert manifest.json()["total_size"] == 10
    assert manifest.json()["assets"] == [
        {
            "id": str(asset.id),
            "content_type": "video/mp4",
            "size_bytes": 10,
            "sha256": "1" * 64,
            "chunk_size": 4 * 1024 * 1024,
            "chunk_count": 1,
        }
    ]
    assert "object_key" not in manifest.content.decode()
    assert "private/offline-video" not in manifest.content.decode()

    license_response = client.post(
        license_url,
        data={"revision_id": str(allowed_revision.id)},
        content_type="application/json",
    )
    assert license_response.status_code == 200
    assert license_response["Cache-Control"] == "private, no-store"
    license_data = license_response.json()
    assert license_data["claims"]["learner_id"] == str(learner.id)
    assert license_data["claims"]["course_id"] == str(course.id)
    assert license_data["claims"]["revision_id"] == str(allowed_revision.id)
    device = Device.objects.get()
    assert license_data["claims"]["device_id"] == str(device.id)
    assert license_data["claims"]["access_pass_id"] == str(device.access_pass_id)
    assert license_data["claims"]["pass_generation"] == device.access_pass.generation
    assert (
        license_data["claims"].get("session_id") is None
        or "session_id" not in license_data["claims"]
    )
    assert (
        license_data["claims"]["expires_at"] - license_data["claims"]["issued_at"] == 24 * 60 * 60
    )
    assert license_data["token"].count(".") == 2
    assert "verification_key" not in license_data
    assert jwt.get_unverified_header(license_data["token"])["alg"] == "ES256"
    assert OfflineLicense.objects.get().pass_generation == device.access_pass.generation

    storage = Mock()
    storage.head.return_value = {"ContentLength": 10}
    storage.read_range.return_value = iter([b"0123"])
    with patch("media_assets.views.get_storage", return_value=storage):
        media_response = client.get(media_url, HTTP_RANGE="bytes=0-3")
    assert media_response.status_code == 206
    assert media_response["Content-Disposition"] == "inline"

    unit.is_downloadable = False
    unit.save(update_fields=("is_downloadable",))
    forbidden_revision = publish_course(course)
    update_response = client.post(
        license_url,
        data={"revision_id": str(allowed_revision.id)},
        content_type="application/json",
    )
    assert update_response.status_code == 409
    assert update_response.json()["code"] == "OFFLINE_REVISION_OUTDATED"
    assert update_response.json()["current_revision_id"] == str(forbidden_revision.id)
    assert update_response.json()["offline_available"] is False
    assert client.get(manifest_url).json()["assets"] == []
    forbidden_url = (
        f"/api/v1/learner/courses/{course.id}/offline-media/{forbidden_revision.id}/{asset.id}"
    )
    assert client.get(forbidden_url).status_code == 404

    enrollment = Enrollment.objects.get(course=course, user=learner)
    enrollment.status = Enrollment.Status.REVOKED
    enrollment.revoked_at = timezone.now()
    enrollment.save(update_fields=("status", "revoked_at"))
    assert (
        client.post(
            license_url,
            data={"revision_id": str(allowed_revision.id)},
            content_type="application/json",
        ).status_code
        == 404
    )


def test_shared_offline_license_fixture_matches_backend_public_key() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "offline_license.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["publicJwk"] == DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK
    claims = jwt.decode(
        fixture["tokens"]["revision-1"],
        jwt.algorithms.ECAlgorithm.from_jwk(fixture["publicJwk"]),
        algorithms=["ES256"],
        options={"verify_exp": False},
    )
    assert claims["revision_id"] == "revision-1"


def test_outdated_offline_license_reports_current_text_course_available(client: Client) -> None:
    _, course, _, token = make_access()
    course.refresh_from_db()
    previous_revision_id = course.current_revision_id
    current_revision = publish_course(course)
    activate(client, token)

    response = client.post(
        f"/api/v1/learner/courses/{course.id}/offline-license",
        data={"revision_id": str(previous_revision_id)},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "OFFLINE_REVISION_OUTDATED",
        "current_revision_id": str(current_revision.id),
        "offline_available": True,
    }
