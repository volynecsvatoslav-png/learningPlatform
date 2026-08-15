import base64
import json
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
import pytest
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import close_old_connections, connections
from django.test import Client
from django.utils import timezone

from accounts.models import User
from config.offline_keys import DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK
from learner.models import (
    AccessLink,
    Enrollment,
    LearnerSession,
    LessonProgress,
    PwaSessionTransfer,
    hash_access_token,
)
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
    enrollment = Enrollment.objects.create(learner=learner, course=course)
    AccessLink.objects.create(enrollment=enrollment, token_hash=hash_access_token(token))
    return learner, course, lesson, token


def session_login(client: Client, token: str) -> None:
    response = client.post(
        "/api/v1/learner/session",
        data={"token": token},
        content_type="application/json",
    )
    assert response.status_code == 200


def create_pwa_transfer(client: Client) -> str:
    response = client.post("/api/v1/learner/pwa-transfer")
    assert response.status_code == 201
    assert response["Cache-Control"] == "private, no-store"
    return str(response.json()["code"])


def test_access_token_is_hashed_and_exchange_creates_server_session(client: Client) -> None:
    learner, course, _, token = make_access()

    assert AccessLink.objects.get().token_hash != token
    session_login(client, token)
    session = LearnerSession.objects.get()
    assert session.learner == learner
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
    session_login(client, token)
    learner_session = LearnerSession.objects.get()
    django_session = Session.objects.get(session_key=learner_session.session_key)
    remaining = (django_session.expire_date - timezone.now()).total_seconds()
    assert settings.LEARNER_SESSION_AGE - 5 <= remaining <= settings.LEARNER_SESSION_AGE


def test_second_device_revokes_first_and_old_session_gets_code(client: Client) -> None:
    _, _, _, token = make_access()
    first = Client()
    second = Client()
    session_login(first, token)
    old_session = LearnerSession.objects.get()
    session_login(second, token)
    old_session.refresh_from_db()
    assert old_session.revoked_at is not None

    response = first.get("/api/v1/learner/courses")
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_REVOKED"
    assert second.get("/api/v1/learner/courses").status_code == 200


def test_pwa_transfer_is_hashed_consumed_once_and_replaces_source_session() -> None:
    learner, _, _, access_token = make_access()
    source = Client()
    destination = Client()
    session_login(source, access_token)
    source_session = LearnerSession.objects.get()

    code = create_pwa_transfer(source)
    transfer = PwaSessionTransfer.objects.get()
    assert transfer.learner == learner
    assert transfer.source_session == source_session
    assert transfer.code_hash != code

    response = destination.post(
        "/api/v1/learner/pwa-transfer/consume",
        data={"code": code},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    transfer.refresh_from_db()
    source_session.refresh_from_db()
    assert transfer.used_at is not None
    assert source_session.revoked_at is not None
    assert LearnerSession.objects.filter(learner=learner, revoked_at__isnull=True).count() == 1
    assert source.get("/api/v1/learner/courses").json()["code"] == "SESSION_REVOKED"
    assert destination.get("/api/v1/learner/courses").status_code == 200

    replay = Client().post(
        "/api/v1/learner/pwa-transfer/consume",
        data={"code": code},
        content_type="application/json",
    )
    assert replay.status_code == 403
    assert replay.json() == {"code": "PWA_TRANSFER_INVALID"}


def test_new_pwa_transfer_invalidates_previous_unused_code() -> None:
    _, _, _, access_token = make_access()
    source = Client()
    session_login(source, access_token)

    first_code = create_pwa_transfer(source)
    first = PwaSessionTransfer.objects.get()
    second_code = create_pwa_transfer(source)
    first.refresh_from_db()
    assert first.used_at is not None

    response = Client().post(
        "/api/v1/learner/pwa-transfer/consume",
        data={"code": first_code},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json() == {"code": "PWA_TRANSFER_INVALID"}
    assert second_code != first_code


def test_expired_pwa_transfer_is_rejected_without_revoking_source() -> None:
    _, _, _, access_token = make_access()
    source = Client()
    session_login(source, access_token)
    source_session = LearnerSession.objects.get()
    code = create_pwa_transfer(source)
    PwaSessionTransfer.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

    response = Client().post(
        "/api/v1/learner/pwa-transfer/consume",
        data={"code": code},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json() == {"code": "PWA_TRANSFER_INVALID"}
    source_session.refresh_from_db()
    assert source_session.revoked_at is None


def test_pwa_transfer_from_revoked_source_session_is_rejected() -> None:
    _, _, _, access_token = make_access()
    source = Client()
    session_login(source, access_token)
    code = create_pwa_transfer(source)
    LearnerSession.objects.update(revoked_at=timezone.now())

    response = Client().post(
        "/api/v1/learner/pwa-transfer/consume",
        data={"code": code},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json() == {"code": "PWA_TRANSFER_INVALID"}
    assert not LearnerSession.objects.filter(revoked_at__isnull=True).exists()


def test_pwa_transfer_attempt_limit_and_server_rate_limit(settings) -> None:  # type: ignore[no-untyped-def]
    _, _, _, access_token = make_access()
    source = Client()
    session_login(source, access_token)
    code = create_pwa_transfer(source)
    public_id, secret = code.split(".", maxsplit=1)
    wrong_secret = ("A" if secret[0] != "A" else "B") + secret[1:]
    wrong_code = f"{public_id}.{wrong_secret}"
    settings.PWA_TRANSFER_MAX_ATTEMPTS = 2

    destination = Client()
    for _ in range(2):
        response = destination.post(
            "/api/v1/learner/pwa-transfer/consume",
            data={"code": wrong_code},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.10",
        )
        assert response.status_code == 403
        assert response.json() == {"code": "PWA_TRANSFER_INVALID"}
    assert PwaSessionTransfer.objects.get().failed_attempts == 2
    assert (
        destination.post(
            "/api/v1/learner/pwa-transfer/consume",
            data={"code": code},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.10",
        ).status_code
        == 403
    )

    cache.clear()
    settings.PWA_TRANSFER_RATE_LIMIT = 1
    first = destination.post(
        "/api/v1/learner/pwa-transfer/consume",
        data={"code": "not-a-code"},
        content_type="application/json",
        REMOTE_ADDR="203.0.113.20",
    )
    limited = destination.post(
        "/api/v1/learner/pwa-transfer/consume",
        data={"code": "not-a-code"},
        content_type="application/json",
        REMOTE_ADDR="203.0.113.20",
    )
    assert first.status_code == 403
    assert limited.status_code == 429
    assert limited.json() == {"code": "PWA_TRANSFER_RATE_LIMITED"}
    assert limited["Cache-Control"] == "private, no-store"


def test_pwa_transfer_rate_limit_is_isolated_by_transfer_id(settings) -> None:  # type: ignore[no-untyped-def]
    cache.clear()
    settings.PWA_TRANSFER_RATE_LIMIT = 1
    destination = Client()

    def code_for(transfer_id: uuid.UUID) -> str:
        public_id = base64.urlsafe_b64encode(transfer_id.bytes).rstrip(b"=").decode("ascii")
        return f"{public_id}.{'x' * 22}"

    first_code = code_for(uuid.uuid4())
    second_code = code_for(uuid.uuid4())
    assert (
        destination.post(
            "/api/v1/learner/pwa-transfer/consume",
            data={"code": first_code},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.40",
        ).status_code
        == 403
    )
    assert (
        destination.post(
            "/api/v1/learner/pwa-transfer/consume",
            data={"code": first_code},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.40",
        ).status_code
        == 429
    )
    assert (
        destination.post(
            "/api/v1/learner/pwa-transfer/consume",
            data={"code": second_code},
            content_type="application/json",
            REMOTE_ADDR="203.0.113.40",
        ).status_code
        == 403
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_pwa_transfer_consume_allows_exactly_one_request() -> None:
    _, _, _, access_token = make_access()
    source = Client()
    session_login(source, access_token)
    code = create_pwa_transfer(source)
    barrier = threading.Barrier(2)

    def consume(address: str) -> tuple[int, dict[str, object]]:
        close_old_connections()
        try:
            destination = Client()
            barrier.wait(timeout=10)
            response = destination.post(
                "/api/v1/learner/pwa-transfer/consume",
                data={"code": code},
                content_type="application/json",
                REMOTE_ADDR=address,
            )
            return response.status_code, response.json()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(consume, ("203.0.113.31", "203.0.113.32")))

    assert sorted(status_code for status_code, _ in results) == [200, 403]
    assert [body for status_code, body in results if status_code == 403] == [
        {"code": "PWA_TRANSFER_INVALID"}
    ]
    assert PwaSessionTransfer.objects.get().used_at is not None
    assert LearnerSession.objects.filter(revoked_at__isnull=True).count() == 1


def test_revoked_enrollment_blocks_course_and_access_link(client: Client) -> None:
    _, course, _, token = make_access()
    enrollment = Enrollment.objects.get(course=course)
    enrollment.status = Enrollment.Status.REVOKED
    enrollment.revoked_at = timezone.now()
    enrollment.save(update_fields=("status", "revoked_at"))

    assert client.get(f"/api/v1/learner/access/{token}").status_code == 404
    response = client.post(
        "/api/v1/learner/session",
        data={"token": token},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ACCESS_REVOKED"


def test_progress_requires_owned_published_lesson_and_persists_completion(client: Client) -> None:
    _, course, lesson, token = make_access()
    session_login(client, token)

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
    session_login(client, token)

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
    session_login(client, token)

    response = client.get("/api/v1/learner/courses")
    assert response.status_code == 200
    assert response.json()[0]["title"] == published_title


def test_foreign_course_and_media_url_are_not_available(client: Client) -> None:
    _, _, _, token = make_access()
    session_login(client, token)
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
        created_by=course.vendor.members.first().user
        if course.vendor.members.exists()
        else User.objects.first(),
    )
    course.cover_asset = asset
    course.save(update_fields=("cover_asset",))
    # The prototype snapshot must contain this asset before learner access is checked.
    lesson.content_units.all().delete()
    ContentUnit.objects.create(
        lesson=lesson,
        type=ContentUnit.Type.IMAGE,
        position=1,
        media_asset=asset,
    )
    publish_course(course)
    session_login(client, token)
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
    publish_course(course)
    content_url = f"/api/v1/learner/courses/{course.id}/media/{asset.id}/content"
    stream_url = f"/api/v1/learner/courses/{course.id}/media/{asset.id}/stream-url"
    assert client.get(content_url).status_code == 401
    session_login(client, token)
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

    enrollment = Enrollment.objects.get(course=course, learner=learner)
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
    session_login(client, token)
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
    assert (
        license_data["claims"]["expires_at"] - license_data["claims"]["issued_at"]
        == 7 * 24 * 60 * 60
    )
    assert license_data["token"].count(".") == 2
    assert "verification_key" not in license_data
    assert jwt.get_unverified_header(license_data["token"])["alg"] == "ES256"

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

    enrollment = Enrollment.objects.get(course=course, learner=learner)
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
    session_login(client, token)

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
