import secrets
from unittest.mock import Mock, patch

import pytest
from django.test import Client
from django.utils import timezone

from accounts.models import User
from learner.models import AccessLink, Enrollment, LearnerSession, LessonProgress, hash_access_token
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


def test_access_token_is_hashed_and_exchange_creates_server_session(client: Client) -> None:
    learner, course, _, token = make_access()

    assert AccessLink.objects.get().token_hash != token
    session_login(client, token)
    session = LearnerSession.objects.get()
    assert session.learner == learner
    assert session.revoked_at is None
    assert client.get("/api/v1/learner/courses").status_code == 200
    assert client.get(f"/api/v1/learner/courses/{course.id}").status_code == 200


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
    session_login(client, token)
    storage = Mock()
    storage.head.return_value = {"ContentLength": 10}
    storage.read_range.return_value = iter([b"234"])
    with patch("media_assets.views.get_storage", return_value=storage):
        response = client.get(
            f"/api/v1/learner/courses/{course.id}/media/{asset.id}/content",
            HTTP_RANGE="bytes=2-4",
        )
    assert response.status_code == 206
    assert response["Content-Range"] == "bytes 2-4/10"
    assert response["Cache-Control"] == "private, no-store"
    assert response["Accept-Ranges"] == "bytes"
    assert b"private/learner-video" not in b"".join(response.streaming_content)
