import base64
import binascii
import hashlib
import hmac
import math
import secrets
import uuid
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.sessions.models import Session
from django.db import transaction
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
from accounts.rate_limit import pwa_transfer_rate_limited
from learner.models import (
    AccessLink,
    Enrollment,
    LearnerSession,
    LessonProgress,
    PwaSessionTransfer,
    hash_access_token,
    hash_pwa_transfer_code,
)
from learner.offline_license import issue_offline_license
from learner.serializers import (
    LearnerProgressSerializer,
    PwaSessionTransferConsumeSerializer,
)
from learning.models import Course, CourseRevision
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


def _private_no_store(response: Response) -> Response:
    response["Cache-Control"] = "private, no-store"
    return response


def _replace_learner_session(request: Request, learner: User) -> LearnerSession:
    now = timezone.now()
    current_session_key = request.session.session_key
    if current_session_key:
        LearnerSession.objects.filter(
            session_key=current_session_key, revoked_at__isnull=True
        ).update(revoked_at=now)
    LearnerSession.objects.filter(learner=learner, revoked_at__isnull=True).update(revoked_at=now)
    request.session.flush()
    login(request._request, learner)
    session_key = request.session.session_key
    if session_key is None:
        raise RuntimeError("Django did not create a learner session")
    return LearnerSession.objects.create(
        learner=learner,
        session_key=session_key,
        device_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
    )


def _new_transfer_code(transfer_id: uuid.UUID) -> str:
    public_id = base64.urlsafe_b64encode(transfer_id.bytes).rstrip(b"=").decode("ascii")
    return f"{public_id}.{secrets.token_urlsafe(16)}"


def _transfer_id(code: str) -> uuid.UUID | None:
    try:
        public_id, secret = code.split(".", maxsplit=1)
        if not secret:
            return None
        decoded = base64.urlsafe_b64decode(public_id + "=" * (-len(public_id) % 4))
        if len(decoded) != 16:
            return None
        return uuid.UUID(bytes=decoded)
    except (ValueError, binascii.Error):
        return None


def _invalid_transfer() -> Response:
    return _private_no_store(
        Response({"code": "PWA_TRANSFER_INVALID"}, status=status.HTTP_403_FORBIDDEN)
    )


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
        return _private_no_store(Response({"csrfToken": get_token(request._request)}))


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
        return _private_no_store(
            Response(
                {
                    "email": link.enrollment.learner.email,
                    "course_title": link.enrollment.course.title,
                    "ready": True,
                }
            )
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
            return _private_no_store(
                Response({"code": "ACCESS_REVOKED"}, status=status.HTTP_403_FORBIDDEN)
            )
        with transaction.atomic():
            learner = User.objects.select_for_update().get(pk=link.enrollment.learner_id)
            _replace_learner_session(request, learner)
        return _private_no_store(
            Response({"ok": True, "course_id": str(link.enrollment.course_id)})
        )


class PwaSessionTransferView(LearnerAPIView):
    def post(self, request: Request) -> Response:
        learner = _learner_user(request)
        source_session = cast(LearnerSession, request.auth)
        transfer_id = uuid.uuid4()
        code = _new_transfer_code(transfer_id)
        now = timezone.now()
        with transaction.atomic():
            locked_learner = User.objects.select_for_update().get(pk=learner.pk)
            locked_source = (
                LearnerSession.objects.select_for_update()
                .filter(
                    pk=source_session.pk,
                    learner=locked_learner,
                    revoked_at__isnull=True,
                )
                .first()
            )
            if locked_source is None:
                raise AuthenticationFailed({"code": "SESSION_REVOKED"}, code="SESSION_REVOKED")
            PwaSessionTransfer.objects.filter(
                source_session=locked_source, used_at__isnull=True
            ).update(used_at=now)
            transfer = PwaSessionTransfer.objects.create(
                id=transfer_id,
                learner=locked_learner,
                source_session=locked_source,
                code_hash=hash_pwa_transfer_code(code),
                expires_at=now + timedelta(seconds=settings.PWA_TRANSFER_TTL_SECONDS),
            )
        return _private_no_store(
            Response(
                {"code": code, "expires_at": transfer.expires_at.isoformat()},
                status=status.HTTP_201_CREATED,
            )
        )


class PwaSessionTransferConsumeView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        if pwa_transfer_rate_limited(request._request):
            response = Response(
                {"code": "PWA_TRANSFER_RATE_LIMITED"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(settings.PWA_TRANSFER_RATE_WINDOW_SECONDS)
            return _private_no_store(response)

        serializer = PwaSessionTransferConsumeSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid_transfer()
        code = serializer.validated_data["code"]
        transfer_id = _transfer_id(code)
        if transfer_id is None:
            return _invalid_transfer()
        learner_id = (
            PwaSessionTransfer.objects.filter(pk=transfer_id)
            .values_list("learner_id", flat=True)
            .first()
        )
        if learner_id is None:
            return _invalid_transfer()

        valid = False
        with transaction.atomic():
            learner = User.objects.select_for_update().get(pk=learner_id)
            transfer = (
                PwaSessionTransfer.objects.select_for_update()
                .select_related("source_session")
                .filter(pk=transfer_id, learner=learner)
                .first()
            )
            now = timezone.now()
            if transfer is None:
                pass
            elif not hmac.compare_digest(transfer.code_hash, hash_pwa_transfer_code(code)):
                if transfer.failed_attempts < settings.PWA_TRANSFER_MAX_ATTEMPTS:
                    transfer.failed_attempts += 1
                    transfer.save(update_fields=("failed_attempts",))
            elif (
                transfer.used_at is not None
                or transfer.expires_at <= now
                or transfer.failed_attempts >= settings.PWA_TRANSFER_MAX_ATTEMPTS
                or transfer.source_session.revoked_at is not None
                or not Session.objects.filter(
                    session_key=transfer.source_session.session_key,
                    expire_date__gt=now,
                ).exists()
            ):
                pass
            else:
                transfer.used_at = now
                transfer.save(update_fields=("used_at",))
                _replace_learner_session(request, learner)
                valid = True
        if not valid:
            return _invalid_transfer()
        return _private_no_store(Response({"ok": True}))


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


def _offline_asset_ids(snapshot: dict[str, Any]) -> set[str]:
    return {
        str(unit["media_asset_id"])
        for module in snapshot.get("modules", [])
        for lesson in module.get("lessons", [])
        for unit in lesson.get("content_units", [])
        if unit.get("media_asset_id") and unit.get("is_downloadable") is True
    }


def _offline_available(snapshot: dict[str, Any]) -> bool:
    return any(
        unit.get("type") == "text"
        or (unit.get("media_asset_id") and unit.get("is_downloadable") is True)
        for module in snapshot.get("modules", [])
        for lesson in module.get("lessons", [])
        for unit in lesson.get("content_units", [])
    )


def _revision_for_course(course: Course, revision_id: object) -> CourseRevision:
    try:
        parsed_revision_id = uuid.UUID(str(revision_id))
    except ValueError as error:
        raise Http404 from error
    revision = CourseRevision.objects.filter(pk=parsed_revision_id, course=course).first()
    if revision is None:
        raise Http404
    return revision


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
        learner_session = cast(LearnerSession, request.auth)
        return Response(
            {
                **snapshot,
                "viewer": {
                    "email": _learner_user(request).email,
                    "session_id": str(learner_session.id)[:8],
                },
            }
        )


class LearnerOfflineManifestView(LearnerAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        enrollment = _active_enrollment(_learner_user(request), course_id)
        revision = enrollment.course.current_revision
        if revision is None:
            raise Http404
        snapshot = cast(dict[str, Any], revision.snapshot_json)
        asset_ids = _offline_asset_ids(snapshot)
        assets = list(
            MediaAsset.objects.filter(
                pk__in=asset_ids,
                vendor_id=enrollment.course.vendor_id,
                status=MediaAsset.Status.READY,
            ).order_by("id")
        )
        if len(assets) != len(asset_ids):
            raise Http404
        chunk_size = 4 * 1024 * 1024
        response = Response(
            {
                "course_id": str(enrollment.course_id),
                "revision_id": str(revision.id),
                "revision": revision.revision_number,
                "snapshot": {
                    **snapshot,
                    "viewer": {
                        "email": _learner_user(request).email,
                        "session_id": str(cast(LearnerSession, request.auth).id)[:8],
                    },
                },
                "assets": [
                    {
                        "id": str(asset.id),
                        "content_type": asset.content_type,
                        "size_bytes": asset.size_bytes,
                        "sha256": asset.sha256,
                        "chunk_size": chunk_size,
                        "chunk_count": math.ceil(asset.size_bytes / chunk_size),
                    }
                    for asset in assets
                ],
                "total_size": sum(asset.size_bytes for asset in assets),
            }
        )
        response["Cache-Control"] = "private, no-store"
        return response


class LearnerOfflineLicenseView(LearnerAPIView):
    def post(self, request: Request, course_id: uuid.UUID) -> Response:
        enrollment = _active_enrollment(_learner_user(request), course_id)
        current_revision = enrollment.course.current_revision
        if current_revision is None:
            raise Http404
        requested_revision_id = request.data.get("revision_id") or current_revision.id
        try:
            parsed_revision_id = uuid.UUID(str(requested_revision_id))
        except ValueError as error:
            raise Http404 from error
        if parsed_revision_id != current_revision.id:
            response = Response(
                {
                    "code": "OFFLINE_REVISION_OUTDATED",
                    "current_revision_id": str(current_revision.id),
                    "offline_available": _offline_available(current_revision.snapshot_json),
                },
                status=status.HTTP_409_CONFLICT,
            )
            response["Cache-Control"] = "private, no-store"
            return response
        license_data = issue_offline_license(
            learner=_learner_user(request),
            course=enrollment.course,
            revision=current_revision,
            session=cast(LearnerSession, request.auth),
        )
        response = Response(
            {
                **license_data,
                "current_revision_id": str(current_revision.id),
                "current_revision": current_revision.revision_number,
                "update_available": False,
            }
        )
        response["Cache-Control"] = "private, no-store"
        return response


class LearnerOfflineMediaContentView(LearnerAPIView):
    def get(
        self,
        request: Request,
        course_id: uuid.UUID,
        revision_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> StreamingHttpResponse:
        enrollment = _active_enrollment(_learner_user(request), course_id)
        revision = _revision_for_course(enrollment.course, revision_id)
        snapshot = cast(dict[str, Any], revision.snapshot_json)
        if str(asset_id) not in _offline_asset_ids(snapshot):
            raise Http404
        asset = MediaAsset.objects.filter(
            pk=asset_id,
            vendor_id=enrollment.course.vendor_id,
            status=MediaAsset.Status.READY,
        ).first()
        if asset is None:
            raise Http404
        return serve_asset_content(request, asset)


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
