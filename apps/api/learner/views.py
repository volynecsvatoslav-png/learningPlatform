import hashlib
import secrets
import uuid
from typing import Any, cast

from django.conf import settings
from django.contrib.auth import login, logout
from django.http import Http404, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from learner.models import (
    AccessLink,
    Enrollment,
    LearnerSession,
    LessonProgress,
    hash_access_token,
)
from learner.serializers import LearnerProgressSerializer
from learning.models import Course
from media_assets.models import MediaAsset
from media_assets.storage import get_storage
from media_assets.views import serve_asset_content


def _active_enrollment(user: User, course_id: uuid.UUID) -> Enrollment:
    enrollment = (
        Enrollment.objects.filter(
            learner=user,
            course_id=course_id,
            status=Enrollment.Status.ACTIVE,
            course__status=Course.Status.PUBLISHED,
        )
        .select_related("course__current_revision")
        .first()
    )
    if enrollment is None:
        raise Http404
    return enrollment


def _learner_user(request: Request) -> User:
    return cast(User, request.user)


class LearnerSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request: Request) -> str:
        return "Session"

    def authenticate(self, request: Request):  # type: ignore[no-untyped-def]
        result = super().authenticate(request)
        if result is None:
            return None
        user, _ = result
        session_key = request.session.session_key
        learner_session = LearnerSession.objects.filter(session_key=session_key).first()
        if learner_session is None or learner_session.learner_id != user.id:
            return None
        if learner_session.revoked_at is not None:
            raise AuthenticationFailed({"code": "SESSION_REVOKED"}, code="SESSION_REVOKED")
        LearnerSession.objects.filter(pk=learner_session.pk).update(last_seen_at=timezone.now())
        return user, learner_session


class LearnerAPIView(APIView):
    authentication_classes = (LearnerSessionAuthentication,)
    permission_classes = (IsAuthenticated,)


class LearnerCsrfView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        return Response({"csrfToken": get_token(request._request)})


class AccessLinkView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request, token: str) -> Response:
        link = (
            AccessLink.objects.filter(token_hash=hash_access_token(token), revoked_at__isnull=True)
            .select_related("enrollment__course")
            .first()
        )
        if link is None or link.enrollment.status != Enrollment.Status.ACTIVE:
            raise Http404
        return Response(
            {
                "email": link.enrollment.learner.email,
                "course_title": link.enrollment.course.title,
                "ready": True,
            }
        )


class LearnerSessionView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        token = str(request.data.get("token", ""))
        link = (
            AccessLink.objects.filter(token_hash=hash_access_token(token), revoked_at__isnull=True)
            .select_related("enrollment__learner", "enrollment__course")
            .first()
        )
        if link is None or link.enrollment.status != Enrollment.Status.ACTIVE:
            return Response({"code": "ACCESS_REVOKED"}, status=status.HTTP_403_FORBIDDEN)
        learner = link.enrollment.learner
        LearnerSession.objects.filter(learner=learner, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        login(request._request, learner)
        session_key = request.session.session_key
        if session_key is None:
            return Response({"code": "SESSION_CREATE_FAILED"}, status=500)
        LearnerSession.objects.create(
            learner=learner,
            session_key=session_key,
            device_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        )
        return Response({"ok": True, "course_id": str(link.enrollment.course_id)})


class LearnerLogoutView(LearnerAPIView):
    def post(self, request: Request) -> Response:
        LearnerSession.objects.filter(
            session_key=request.session.session_key, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        logout(request._request)
        return Response({"ok": True})


def _snapshot_course(enrollment: Enrollment) -> dict[str, Any]:
    revision = enrollment.course.current_revision
    if revision is None:
        raise Http404
    return cast(dict[str, Any], revision.snapshot_json)


class LearnerCourseListView(LearnerAPIView):
    def get(self, request: Request) -> Response:
        enrollments = (
            Enrollment.objects.filter(
                learner=_learner_user(request),
                status=Enrollment.Status.ACTIVE,
                course__status=Course.Status.PUBLISHED,
            )
            .select_related("course__current_revision")
            .order_by("course__title")
        )
        return Response(
            [
                {
                    "id": str(enrollment.course_id),
                    "title": enrollment.course.current_revision.snapshot_json["title"],
                    "short_description": enrollment.course.current_revision.snapshot_json[
                        "short_description"
                    ],
                    "description_markdown": enrollment.course.current_revision.snapshot_json[
                        "description_markdown"
                    ],
                    "cover_asset_id": enrollment.course.current_revision.snapshot_json.get(
                        "cover_asset_id"
                    ),
                }
                for enrollment in enrollments
                if enrollment.course.current_revision is not None
            ]
        )


class LearnerCourseDetailView(LearnerAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        enrollment = _active_enrollment(_learner_user(request), course_id)
        snapshot = _snapshot_course(enrollment)
        return Response(snapshot)


class LearnerProgressView(LearnerAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        _active_enrollment(_learner_user(request), course_id)
        rows = LessonProgress.objects.filter(learner=_learner_user(request), course_id=course_id)
        return Response(LearnerProgressSerializer(rows, many=True).data)

    def post(self, request: Request, course_id: uuid.UUID, lesson_id: uuid.UUID) -> Response:
        enrollment = _active_enrollment(_learner_user(request), course_id)
        snapshot = _snapshot_course(enrollment)
        lesson_exists = any(
            lesson["id"] == str(lesson_id)
            for module in snapshot.get("modules", [])
            for lesson in module.get("lessons", [])
        )
        if not lesson_exists:
            raise Http404
        serializer = LearnerProgressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        percent = serializer.validated_data["percent"]
        completed = serializer.validated_data.get("status") == "completed" or percent == 100
        progress, _ = LessonProgress.objects.get_or_create(
            learner=_learner_user(request),
            lesson_id=lesson_id,
            defaults={
                "course": enrollment.course,
                "percent": percent,
                "status": "completed" if completed else "in_progress",
                "completed_at": timezone.now() if completed else None,
            },
        )
        if progress.status != "completed":
            progress.course = enrollment.course
            progress.percent = max(progress.percent, percent)
            progress.status = "completed" if completed else "in_progress"
            progress.completed_at = timezone.now() if completed else None
            progress.save()
        return Response(LearnerProgressSerializer(progress).data)


class LearnerStreamURLView(LearnerAPIView):
    def get(self, request: Request, course_id: uuid.UUID, asset_id: uuid.UUID) -> Response:
        enrollment = _active_enrollment(_learner_user(request), course_id)
        snapshot = _snapshot_course(enrollment)
        asset_ids = {snapshot.get("cover_asset_id")}
        for module in snapshot.get("modules", []):
            for lesson in module.get("lessons", []):
                for unit in lesson.get("content_units", []):
                    if unit.get("media_asset_id"):
                        asset_ids.add(unit["media_asset_id"])
        if str(asset_id) not in asset_ids:
            raise Http404
        asset = MediaAsset.objects.filter(
            pk=asset_id, vendor_id=enrollment.course.vendor_id, status=MediaAsset.Status.READY
        ).first()
        if asset is None:
            raise Http404
        url = (
            f"/api/v1/learner/courses/{course_id}/media/{asset_id}/content"
            if settings.MEDIA_TRANSFER_MODE == "proxy"
            else get_storage().create_download_url(key=asset.object_key)
        )
        response = Response({"url": url})
        response["Cache-Control"] = "no-store"
        return response


class LearnerMediaContentView(LearnerAPIView):
    def get(
        self, request: Request, course_id: uuid.UUID, asset_id: uuid.UUID
    ) -> StreamingHttpResponse:
        enrollment = _active_enrollment(_learner_user(request), course_id)
        snapshot = _snapshot_course(enrollment)
        asset_ids = {snapshot.get("cover_asset_id")}
        for module in snapshot.get("modules", []):
            for lesson in module.get("lessons", []):
                for unit in lesson.get("content_units", []):
                    asset_ids.add(unit.get("media_asset_id"))
        if str(asset_id) not in asset_ids:
            raise Http404
        asset = MediaAsset.objects.filter(
            pk=asset_id, vendor_id=enrollment.course.vendor_id, status=MediaAsset.Status.READY
        ).first()
        if asset is None:
            raise Http404
        return serve_asset_content(request, asset)
