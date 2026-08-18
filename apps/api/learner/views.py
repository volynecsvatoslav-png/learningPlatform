import math
import uuid
from typing import Any, cast

from django.conf import settings
from django.contrib.auth import logout
from django.http import Http404, HttpResponseBase
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

from accounts.rate_limit import (
    heartbeat_rate_limited,
    learner_auth_rate_limited,
    media_url_rate_limited,
    recovery_request_rate_limited,
)
from learner.models import (
    AccessPass,
    Enrollment,
    LearnerSession,
    LessonProgress,
)
from learner.offline_license import issue_offline_license
from learner.serializers import (
    AccessExchangeSerializer,
    AccessInspectSerializer,
    LearnerProgressSerializer,
    RecoveryExchangeSerializer,
)
from learner.services import (
    DeviceProofError,
    InvalidAccessLink,
    InvalidRecoveryToken,
    LearnerAuthContext,
    TransferConfirmationRequired,
    exchange_access,
    inspect_access,
    recover_access,
    request_recovery,
    write_audit,
)
from learning.models import Course, CourseRevision
from media_assets.models import MediaAsset
from media_assets.storage import get_storage
from media_assets.views import serve_asset_content


def _learner_context(request: Request) -> LearnerAuthContext:
    return cast(LearnerAuthContext, request.auth)


def _private_no_store(response: Response) -> Response:
    response["Cache-Control"] = "private, no-store"
    return response


def _active_enrollment(context: LearnerAuthContext, course_id: uuid.UUID) -> Enrollment:
    enrollment = (
        Enrollment.objects.filter(
            user=context.learner,
            vendor=context.access_pass.vendor,
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


class LearnerSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request: Request) -> str:
        return "Session"

    def authenticate(self, request: Request):  # type: ignore[no-untyped-def]
        result = super().authenticate(request)
        if result is None:
            return None
        user, _ = result
        session_key = request.session.session_key
        if not session_key:
            return None
        learner_session = (
            LearnerSession.objects.filter(session_key=session_key)
            .select_related("access_pass", "access_pass__vendor", "device")
            .first()
        )
        if learner_session is None or learner_session.learner_id != user.id:
            return None
        if learner_session.access_pass is None or learner_session.device is None:
            return None
        now = timezone.now()
        if (
            learner_session.expires_at is not None
            and learner_session.expires_at <= now
            and learner_session.revoked_at is None
        ):
            LearnerSession.objects.filter(pk=learner_session.pk, revoked_at__isnull=True).update(
                revoked_at=now, revoke_reason=LearnerSession.RevokeReason.EXPIRED
            )
            raise AuthenticationFailed({"code": "SESSION_EXPIRED"}, code="SESSION_EXPIRED")
        if learner_session.revoked_at is not None:
            code = (
                "SESSION_REPLACED"
                if learner_session.revoke_reason == LearnerSession.RevokeReason.REPLACED
                else "SESSION_REVOKED"
            )
            raise AuthenticationFailed({"code": code}, code=code)
        if learner_session.access_pass.status != AccessPass.Status.ACTIVE:
            raise AuthenticationFailed({"code": "SESSION_REVOKED"}, code="SESSION_REVOKED")
        if (
            learner_session.device.revoked_at is not None
            or learner_session.pass_generation != learner_session.access_pass.generation
        ):
            raise AuthenticationFailed({"code": "SESSION_REPLACED"}, code="SESSION_REPLACED")
        LearnerSession.objects.filter(pk=learner_session.pk).update(last_seen_at=now)
        return user, LearnerAuthContext(
            learner=user,
            session=learner_session,
            access_pass=learner_session.access_pass,
            device=learner_session.device,
        )


class LearnerAPIView(APIView):
    authentication_classes = (LearnerSessionAuthentication,)
    permission_classes = (IsAuthenticated,)


class LearnerCsrfView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        return _private_no_store(Response({"csrfToken": get_token(request._request)}))


class AccessInspectView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        if learner_auth_rate_limited(request._request, "inspect"):
            return _rate_limited()
        serializer = AccessInspectSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_error(serializer.errors)
        data = serializer.validated_data
        try:
            access_pass, challenge, device_match, transfer_required = inspect_access(
                token=str(data["token"]),
                installation_id=data["installation_id"],
                public_key_jwk=data["public_key_jwk"],
            )
        except InvalidAccessLink:
            return _private_no_store(
                Response({"code": "INVALID_ACCESS_LINK"}, status=status.HTTP_404_NOT_FOUND)
            )
        return _private_no_store(
            Response(
                {
                    "challenge": challenge.challenge,
                    "transfer_required": transfer_required,
                    "device_match": device_match,
                    "generation": access_pass.generation,
                }
            )
        )


class AccessExchangeView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        if learner_auth_rate_limited(request._request, "exchange"):
            return _rate_limited()
        serializer = AccessExchangeSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_error(serializer.errors)
        data = serializer.validated_data
        try:
            result = exchange_access(
                request=request._request,
                token=str(data["token"]),
                installation_id=data["installation_id"],
                public_key_jwk=data["public_key_jwk"],
                challenge_value=str(data["challenge"]),
                signature=str(data["signature"]),
                confirm_transfer=bool(data.get("confirm_transfer", False)),
            )
        except InvalidAccessLink:
            return _private_no_store(
                Response({"code": "INVALID_ACCESS_LINK"}, status=status.HTTP_404_NOT_FOUND)
            )
        except DeviceProofError:
            return _private_no_store(
                Response({"code": "DEVICE_PROOF_INVALID"}, status=status.HTTP_401_UNAUTHORIZED)
            )
        except TransferConfirmationRequired:
            return _private_no_store(
                Response(
                    {
                        "code": "DEVICE_TRANSFER_CONFIRMATION_REQUIRED",
                        "message": "Доступ уже открыт на другом устройстве. "
                        "Продолжить здесь и завершить предыдущую сессию?",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            )
        return _private_no_store(
            Response(
                {
                    "ok": True,
                    "generation": result.access_pass.generation,
                    "transfer_performed": result.transfer_performed,
                }
            )
        )


class AuthMeView(LearnerAPIView):
    def get(self, request: Request) -> Response:
        context = _learner_context(request)
        return _private_no_store(
            Response(
                {
                    "email": context.learner.email,
                    "vendor_id": str(context.access_pass.vendor_id),
                    "vendor_name": context.access_pass.vendor.name,
                    "device_id": str(context.device.id),
                    "installation_id": str(context.device.installation_id),
                    "generation": context.access_pass.generation,
                }
            )
        )


class AuthHeartbeatView(LearnerAPIView):
    def post(self, request: Request) -> Response:
        context = _learner_context(request)
        session_key = request.session.session_key
        if session_key is not None and heartbeat_rate_limited(request._request, session_key):
            return _rate_limited()
        now = timezone.now()
        AccessPass.objects.filter(pk=context.access_pass.pk).update(last_used_at=now)
        return _private_no_store(
            Response(
                {
                    "ok": True,
                    "generation": context.access_pass.generation,
                    "expires_at": context.session.expires_at.isoformat()
                    if context.session.expires_at
                    else None,
                }
            )
        )


class LearnerLogoutView(LearnerAPIView):
    def post(self, request: Request) -> Response:
        context = _learner_context(request)
        LearnerSession.objects.filter(pk=context.session.pk, revoked_at__isnull=True).update(
            revoked_at=timezone.now(), revoke_reason=LearnerSession.RevokeReason.LOGOUT
        )
        write_audit(
            event_type="learner_logout",
            vendor=context.access_pass.vendor,
            actor=context.learner,
            target_type="LearnerSession",
            target_id=context.session.id,
            request=request._request,
        )
        logout(request._request)
        return _private_no_store(Response({"ok": True}))


class RecoveryRequestView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        email = str(request.data.get("email", "")).strip()
        if not email:
            return _validation_error({"email": "Email is required."})
        ip_limited, email_limited = recovery_request_rate_limited(request._request, email)
        if not ip_limited and not email_limited:
            request_recovery(email=email, request=request._request)
        return _private_no_store(
            Response(
                {
                    "ok": True,
                    "message": "Если доступ существует, письмо отправлено.",
                }
            )
        )


class RecoveryExchangeView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        if learner_auth_rate_limited(request._request, "recovery-exchange"):
            return _rate_limited()
        serializer = RecoveryExchangeSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_error(serializer.errors)
        data = serializer.validated_data
        try:
            access_pass, raw_token = recover_access(
                request=request._request,
                recovery_token=str(data["recovery_token"]),
                installation_id=data["installation_id"],
                public_key_jwk=data["public_key_jwk"],
                signature=str(data["signature"]),
            )
        except InvalidRecoveryToken:
            return _private_no_store(
                Response({"code": "INVALID_RECOVERY_TOKEN"}, status=status.HTTP_404_NOT_FOUND)
            )
        except DeviceProofError:
            return _private_no_store(
                Response({"code": "DEVICE_PROOF_INVALID"}, status=status.HTTP_401_UNAUTHORIZED)
            )
        return _private_no_store(
            Response(
                {
                    "ok": True,
                    "access_token": raw_token,
                    "access_link": f"{settings.PUBLIC_APP_URL}/app/#access={raw_token}",
                    "generation": access_pass.generation,
                }
            )
        )


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


def _viewer(context: LearnerAuthContext) -> dict[str, str]:
    return {
        "email": context.learner.email,
        "session_id": str(context.session.id)[:8],
    }


class LearnerCourseListView(LearnerAPIView):
    def get(self, request: Request) -> Response:
        context = _learner_context(request)
        enrollments = (
            Enrollment.objects.filter(
                user=context.learner,
                vendor=context.access_pass.vendor,
                status=Enrollment.Status.ACTIVE,
                course__status=Course.Status.PUBLISHED,
            )
            .select_related("course__current_revision")
            .order_by("course__title")
        )
        return _private_no_store(
            Response(
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
        )


class LearnerCourseDetailView(LearnerAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        context = _learner_context(request)
        enrollment = _active_enrollment(context, course_id)
        snapshot = _snapshot_course(enrollment)
        return _private_no_store(Response({**snapshot, "viewer": _viewer(context)}))


class LearnerOfflineManifestView(LearnerAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        context = _learner_context(request)
        enrollment = _active_enrollment(context, course_id)
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
                "snapshot": {**snapshot, "viewer": _viewer(context)},
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
        return _private_no_store(response)


class LearnerOfflineLicenseView(LearnerAPIView):
    def post(self, request: Request, course_id: uuid.UUID) -> Response:
        context = _learner_context(request)
        enrollment = _active_enrollment(context, course_id)
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
            return _private_no_store(response)
        license_data = issue_offline_license(
            learner=context.learner,
            access_pass=context.access_pass,
            device=context.device,
            course=enrollment.course,
            revision=current_revision,
        )
        response = Response(
            {
                **license_data,
                "current_revision_id": str(current_revision.id),
                "current_revision": current_revision.revision_number,
                "update_available": False,
            }
        )
        return _private_no_store(response)


class LearnerOfflineMediaContentView(LearnerAPIView):
    def get(
        self,
        request: Request,
        course_id: uuid.UUID,
        revision_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> HttpResponseBase:
        context = _learner_context(request)
        if media_url_rate_limited(request._request, context.session.session_key):
            return _rate_limited(settings.MEDIA_URL_RATE_WINDOW_SECONDS)
        enrollment = _active_enrollment(context, course_id)
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
        context = _learner_context(request)
        _active_enrollment(context, course_id)
        rows = LessonProgress.objects.filter(
            learner=context.learner,
            course_id=course_id,
            course__vendor=context.access_pass.vendor,
        )
        return Response(LearnerProgressSerializer(rows, many=True).data)

    def post(self, request: Request, course_id: uuid.UUID, lesson_id: uuid.UUID) -> Response:
        context = _learner_context(request)
        enrollment = _active_enrollment(context, course_id)
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
            learner=context.learner,
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
        context = _learner_context(request)
        if media_url_rate_limited(request._request, context.session.session_key):
            return _rate_limited(settings.MEDIA_URL_RATE_WINDOW_SECONDS)
        enrollment = _active_enrollment(context, course_id)
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
    def get(self, request: Request, course_id: uuid.UUID, asset_id: uuid.UUID) -> HttpResponseBase:
        context = _learner_context(request)
        if media_url_rate_limited(request._request, context.session.session_key):
            return _rate_limited(settings.MEDIA_URL_RATE_WINDOW_SECONDS)
        enrollment = _active_enrollment(context, course_id)
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


def _rate_limited(window_seconds: int | None = None) -> Response:
    response = Response({"code": "RATE_LIMITED"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    response["Retry-After"] = str(window_seconds or settings.ACCESS_AUTH_RATE_WINDOW_SECONDS)
    return _private_no_store(response)


def _validation_error(errors: dict[str, Any]) -> Response:
    return _private_no_store(
        Response({"code": "VALIDATION_ERROR", "errors": errors}, status=status.HTTP_400_BAD_REQUEST)
    )
