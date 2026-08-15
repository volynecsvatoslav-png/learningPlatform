import secrets
import uuid
from typing import Any, cast

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import Http404
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_protect
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.rate_limit import auth_rate_limited
from learner.models import AccessLink, Enrollment, LearnerSession, hash_access_token
from learning.models import ContentUnit, Course, Lesson, Module
from learning.services import (
    PublicationValidationError,
    create_content_unit,
    create_lesson,
    create_module,
    delete_content_unit,
    delete_lesson,
    delete_module,
    move_content_unit,
    move_lesson,
    move_module,
    publish_course,
)
from media_assets.models import MediaAsset
from media_assets.serializers import MediaAssetSerializer
from vendor_api.serializers import (
    AccessGrantSerializer,
    EnrollmentSerializer,
    StructureSerializer,
    VendorContentUnitSerializer,
    VendorCourseSerializer,
    VendorLessonSerializer,
    VendorMemberSerializer,
    VendorMemberWriteSerializer,
    VendorModuleSerializer,
)
from vendors.models import VendorMember
from vendors.policies import VendorContext


class CsrfSessionAuthentication(SessionAuthentication):
    def authenticate(self, request: Request):  # type: ignore[no-untyped-def]
        result = super().authenticate(request)
        if (
            result is not None
            and LearnerSession.objects.filter(session_key=request.session.session_key).exists()
        ):
            return None
        return result


class VendorAPIView(APIView):
    authentication_classes = (CsrfSessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    def context(
        self,
        request: Request,
        *,
        vendor_id: uuid.UUID | None = None,
        roles: tuple[str, ...] | None = None,
    ) -> Any:
        value = (
            vendor_id or request.headers.get("X-Vendor-ID") or request.query_params.get("vendor_id")
        )
        if not value:
            raise Http404
        try:
            parsed = uuid.UUID(str(value))
        except ValueError as error:
            raise Http404 from error
        return VendorContext.resolve(user=cast(User, request.user), vendor_id=parsed, roles=roles)


def _send_access_link(enrollment: Enrollment) -> str:
    token = secrets.token_urlsafe(32)
    AccessLink.objects.filter(enrollment=enrollment, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    AccessLink.objects.create(enrollment=enrollment, token_hash=hash_access_token(token))
    url = f"{settings.PUBLIC_APP_URL}/app/#access={token}"
    send_mail(
        subject=f"Доступ к курсу: {enrollment.course.title}",
        message=f"Откройте ссылку для входа: {url}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[enrollment.learner.email],
    )
    return url


class VendorCsrfView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        response = Response({"csrfToken": get_token(request._request)})
        return response


class VendorAuthView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        if auth_rate_limited(request._request, "login"):
            return Response({"code": "AUTH_RATE_LIMITED"}, status=429)
        email = str(request.data.get("email", ""))
        password = str(request.data.get("password", ""))
        user = authenticate(request._request, username=email, password=password)
        if user is None or not user.vendor_memberships.filter(vendor__status="active").exists():
            return Response({"code": "INVALID_CREDENTIALS"}, status=401)
        login(request._request, user)
        return Response({"ok": True})


class VendorPasswordResetRequestView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        limited = auth_rate_limited(request._request, "password-reset")
        email = User.objects.normalize_email_address(str(request.data.get("email", "")))
        if not limited:
            user = (
                User.objects.filter(email=email, is_active=True)
                .filter(vendor_memberships__vendor__status="active")
                .distinct()
                .first()
            )
            if user is not None and user.has_usable_password():
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                url = f"{settings.PUBLIC_APP_URL}/vendor/reset/{uid}/{token}"
                send_mail(
                    subject="Восстановление пароля",
                    message=f"Откройте ссылку для восстановления пароля: {url}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                )
        return Response({"ok": True})


class VendorPasswordResetConfirmView(APIView):
    permission_classes = (AllowAny,)

    @method_decorator(csrf_protect)
    def post(self, request: Request, uidb64: str, token: str) -> Response:
        try:
            user_id = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=user_id, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({"code": "INVALID_RESET_LINK"}, status=400)
        if not default_token_generator.check_token(user, token):
            return Response({"code": "INVALID_RESET_LINK"}, status=400)
        password = str(request.data.get("password", ""))
        try:
            validate_password(password, user=user)
        except DjangoValidationError as error:
            return Response(
                {"code": "PASSWORD_INVALID", "password": list(error.messages)}, status=400
            )
        user.set_password(password)
        user.save(update_fields=("password", "updated_at"))
        return Response({"ok": True})


class VendorLogoutView(VendorAPIView):
    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response({"ok": True})


class VendorMeView(VendorAPIView):
    def get(self, request: Request) -> Response:
        memberships = VendorMember.objects.filter(
            user=cast(User, request.user), vendor__status="active"
        ).select_related("vendor")
        if not memberships.exists():
            return Response({"code": "VENDOR_ACCESS_REQUIRED"}, status=403)
        return Response(
            {
                "email": cast(User, request.user).email,
                "vendors": [
                    {"id": str(m.vendor_id), "name": m.vendor.name, "role": m.role}
                    for m in memberships
                ],
            }
        )


def _course_context(
    request: Request, course_id: uuid.UUID, roles: tuple[str, ...] | None = None
) -> tuple[Any, Course]:
    course = Course.objects.filter(pk=course_id).first()
    if course is None:
        raise Http404
    context = VendorAPIView().context(request, vendor_id=course.vendor_id, roles=roles)
    return context, context.get_object_or_404(Course.objects, pk=course_id)


def _cover_for_vendor(vendor_id: uuid.UUID, asset_id: object) -> MediaAsset | None:
    if asset_id is None:
        return None
    return MediaAsset.objects.filter(
        pk=cast(uuid.UUID, asset_id),
        vendor_id=vendor_id,
        status=MediaAsset.Status.READY,
        kind=MediaAsset.Kind.IMAGE,
    ).first()


class VendorCourseListView(VendorAPIView):
    def get(self, request: Request) -> Response:
        context = self.context(request)
        courses = context.scope(Course.objects).select_related("current_revision")
        return Response(VendorCourseSerializer(courses, many=True).data)

    def post(self, request: Request) -> Response:
        context = self.context(request, roles=(VendorMember.Role.OWNER, VendorMember.Role.EDITOR))
        serializer = VendorCourseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        cover_id = data.pop("cover_asset_id", None)
        cover = _cover_for_vendor(context.vendor.id, cover_id)
        if cover_id is not None and cover is None:
            return Response({"code": "MEDIA_NOT_READY"}, status=409)
        course = Course.objects.create(vendor=context.vendor, cover_asset=cover, **data)
        return Response(VendorCourseSerializer(course).data, status=201)


class VendorCourseDetailView(VendorAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(request, course_id)
        return Response(VendorCourseSerializer(course).data)

    def patch(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(
            request, course_id, (VendorMember.Role.OWNER, VendorMember.Role.EDITOR)
        )
        serializer = VendorCourseSerializer(course, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "cover_asset_id" in data:
            cover_id = data.pop("cover_asset_id")
            cover = _cover_for_vendor(course.vendor_id, cover_id)
            if cover_id is not None and cover is None:
                return Response({"code": "MEDIA_NOT_READY"}, status=409)
            data["cover_asset"] = cover
        for field, value in data.items():
            setattr(course, field, value)
        course.full_clean()
        course.save()
        return Response(VendorCourseSerializer(course).data)

    def delete(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(
            request, course_id, (VendorMember.Role.OWNER, VendorMember.Role.EDITOR)
        )
        course.archive()
        return Response(status=204)


class VendorCoursePublishView(VendorAPIView):
    def post(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(
            request, course_id, (VendorMember.Role.OWNER, VendorMember.Role.EDITOR)
        )
        try:
            revision = publish_course(course, created_by=request.user)
        except PublicationValidationError as error:
            return Response({"code": "PUBLICATION_INVALID", "detail": str(error)}, status=422)
        return Response({"revision": revision.revision_number, "status": course.Status.PUBLISHED})


class VendorCoursePreviewView(VendorAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(request, course_id)
        if course.current_revision is None:
            return Response({"code": "NO_PUBLISHED_REVISION"}, status=404)
        return Response(course.current_revision.snapshot_json)


class VendorCourseArchiveView(VendorAPIView):
    def post(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(
            request, course_id, (VendorMember.Role.OWNER, VendorMember.Role.EDITOR)
        )
        course.archive()
        return Response(VendorCourseSerializer(course).data)


class VendorCourseRestoreView(VendorAPIView):
    def post(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(
            request, course_id, (VendorMember.Role.OWNER, VendorMember.Role.EDITOR)
        )
        course.status = (
            Course.Status.PUBLISHED if course.current_revision_id else Course.Status.DRAFT
        )
        course.save(update_fields=("status", "updated_at"))
        return Response(VendorCourseSerializer(course).data)


class VendorCourseStructureView(VendorAPIView):
    def get(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(request, course_id)
        modules = Module.objects.filter(course=course).prefetch_related("lessons__content_units")
        return Response(
            {
                "modules": [
                    {
                        **VendorModuleSerializer(module).data,
                        "lessons": [
                            {
                                **VendorLessonSerializer(lesson).data,
                                "content_units": VendorContentUnitSerializer(
                                    lesson.content_units.all(), many=True
                                ).data,
                            }
                            for lesson in module.lessons.all()
                        ],
                    }
                    for module in modules
                ]
            }
        )

    def post(self, request: Request, course_id: uuid.UUID) -> Response:
        _, course = _course_context(
            request, course_id, (VendorMember.Role.OWNER, VendorMember.Role.EDITOR)
        )
        serializer = StructureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entity, action = data["entity"], data["action"]
        if entity == "module":
            module_item = (
                Module.objects.filter(pk=data.get("id"), course=course).first()
                if data.get("id")
                else None
            )
            if action == "create":
                module_item = create_module(
                    course,
                    position=data.get("position"),
                    title=data.get("title", ""),
                    description=data.get("description", ""),
                )
            elif module_item is None:
                raise Http404
            elif action == "delete":
                delete_module(module_item)
                return Response(status=204)
            elif action == "move":
                module_item = move_module(module_item, data["position"])
            else:
                for field in ("title", "description"):
                    if field in data:
                        setattr(module_item, field, data[field])
                module_item.save(update_fields=("title", "description"))
            return Response(
                VendorModuleSerializer(module_item).data, status=201 if action == "create" else 200
            )
        if entity == "lesson":
            lesson_item: Lesson | None = None
            module = (
                Module.objects.filter(pk=data.get("parent_id"), course=course).first()
                if data.get("parent_id")
                else None
            )
            if action == "create":
                if module is None:
                    raise Http404
                lesson_item = create_lesson(
                    module,
                    position=data.get("position"),
                    title=data.get("title", ""),
                    description=data.get("description", ""),
                    is_published=data.get("is_published", False),
                )
            else:
                lesson_item = Lesson.objects.filter(
                    pk=data.get("id"), module__course=course
                ).first()
            if lesson_item is None:
                raise Http404
            if action == "delete":
                delete_lesson(lesson_item)
                return Response(status=204)
            elif action == "move":
                lesson_item = move_lesson(lesson_item, data["position"])
            else:
                for field in ("title", "description", "is_published"):
                    if field in data:
                        setattr(lesson_item, field, data[field])
                lesson_item.save(update_fields=("title", "description", "is_published"))
            return Response(
                VendorLessonSerializer(lesson_item).data,
                status=201 if action == "create" else 200,
            )
        lesson = (
            Lesson.objects.filter(pk=data.get("parent_id"), module__course=course).first()
            if data.get("parent_id")
            else None
        )
        unit_item: ContentUnit | None = None
        if action == "create":
            if lesson is None:
                raise Http404
            content_type = data["type"]
            asset = self._content_asset(course, content_type, data.get("media_asset_id"))
            if content_type != ContentUnit.Type.TEXT and asset is None:
                return Response({"code": "MEDIA_NOT_READY"}, status=409)
            try:
                unit_item = create_content_unit(
                    lesson,
                    position=data.get("position"),
                    type=content_type,
                    title=data.get("title", ""),
                    text_markdown=data.get("text_markdown")
                    if content_type == ContentUnit.Type.TEXT
                    else None,
                    media_asset=asset,
                    is_downloadable=data.get("is_downloadable", False),
                )
            except DjangoValidationError as error:
                raise DRFValidationError(error.message_dict) from error
        else:
            unit_item = ContentUnit.objects.filter(
                pk=data.get("id"), lesson__module__course=course
            ).first()
        if unit_item is None:
            raise Http404
        if action == "delete":
            delete_content_unit(unit_item)
            return Response(status=204)
        elif action == "move":
            unit_item = move_content_unit(unit_item, data["position"])
        else:
            target_type = data.get("type", unit_item.type)
            for field in ("title", "is_downloadable"):
                if field in data:
                    setattr(unit_item, field, data[field])
            unit_item.type = target_type
            if target_type == ContentUnit.Type.TEXT:
                if "text_markdown" in data:
                    unit_item.text_markdown = data["text_markdown"]
                unit_item.media_asset = None
            elif "media_asset_id" in data:
                asset = self._content_asset(course, target_type, data.get("media_asset_id"))
                if asset is None:
                    return Response({"code": "MEDIA_NOT_READY"}, status=409)
                unit_item.media_asset = asset
                unit_item.text_markdown = None
            try:
                unit_item.full_clean()
            except DjangoValidationError as error:
                raise DRFValidationError(error.message_dict) from error
            unit_item.save()
        return Response(
            VendorContentUnitSerializer(unit_item).data,
            status=201 if action == "create" else 200,
        )

    @staticmethod
    def _content_asset(course: Course, content_type: object, asset_id: object) -> MediaAsset | None:
        if not asset_id:
            return None
        return MediaAsset.objects.filter(
            pk=cast(uuid.UUID, asset_id),
            vendor=course.vendor,
            status=MediaAsset.Status.READY,
            kind=content_type,
        ).first()


def _enrollment_for_vendor(request: Request, enrollment_id: uuid.UUID) -> tuple[Any, Enrollment]:
    enrollment = Enrollment.objects.filter(pk=enrollment_id).select_related("course").first()
    if enrollment is None:
        raise Http404
    return _course_context(request, enrollment.course_id, (VendorMember.Role.OWNER,)), enrollment


class VendorAccessListView(VendorAPIView):
    def get(self, request: Request) -> Response:
        context = self.context(request, roles=(VendorMember.Role.OWNER,))
        rows = Enrollment.objects.filter(course__vendor=context.vendor).select_related(
            "course", "learner"
        )
        return Response(EnrollmentSerializer(rows, many=True).data)


class VendorAccessGrantView(VendorAPIView):
    def post(self, request: Request) -> Response:
        serializer = AccessGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = self.context(
            request, vendor_id=data["vendor_id"], roles=(VendorMember.Role.OWNER,)
        )
        courses = list(
            Course.objects.filter(
                pk__in=data["course_ids"],
                vendor=context.vendor,
                status=Course.Status.PUBLISHED,
            )
        )
        if len(courses) != len(set(data["course_ids"])):
            raise Http404
        learner, _ = User.objects.get_or_create(
            email=User.objects.normalize_email_address(data["learner_email"])
        )
        result = []
        for course in courses:
            enrollment, _ = Enrollment.objects.update_or_create(
                learner=learner,
                course=course,
                defaults={
                    "status": Enrollment.Status.ACTIVE,
                    "revoked_at": None,
                    "granted_by": request.user,
                },
            )
            _send_access_link(enrollment)
            result.append(enrollment)
        return Response(EnrollmentSerializer(result, many=True).data, status=201)


class VendorAccessRevokeView(VendorAPIView):
    def post(self, request: Request, enrollment_id: uuid.UUID) -> Response:
        _, enrollment = _enrollment_for_vendor(request, enrollment_id)
        enrollment.status = Enrollment.Status.REVOKED
        enrollment.revoked_at = timezone.now()
        enrollment.save(update_fields=("status", "revoked_at"))
        AccessLink.objects.filter(enrollment=enrollment, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        return Response(EnrollmentSerializer(enrollment).data)


class VendorAccessReissueView(VendorAPIView):
    def post(self, request: Request, enrollment_id: uuid.UUID) -> Response:
        _, enrollment = _enrollment_for_vendor(request, enrollment_id)
        if enrollment.status != Enrollment.Status.ACTIVE:
            return Response({"code": "ENROLLMENT_REVOKED"}, status=409)
        _send_access_link(enrollment)
        return Response(EnrollmentSerializer(enrollment).data)


class VendorMemberListView(VendorAPIView):
    def get(self, request: Request) -> Response:
        context = self.context(request, roles=(VendorMember.Role.OWNER,))
        rows = VendorMember.objects.filter(vendor=context.vendor).select_related("user")
        return Response(VendorMemberSerializer(rows, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = VendorMemberWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = self.context(
            request, vendor_id=data["vendor_id"], roles=(VendorMember.Role.OWNER,)
        )
        email = User.objects.normalize_email_address(data["email"])
        if User.objects.filter(email=email).exists():
            return Response({"code": "MEMBER_EMAIL_CONFLICT"}, status=409)
        candidate = User(email=email)
        try:
            validate_password(data["password"], user=candidate)
        except DjangoValidationError as error:
            return Response(
                {"code": "PASSWORD_INVALID", "password": list(error.messages)}, status=400
            )
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email,
                    data["password"],
                    email_verified_at=timezone.now(),
                )
                member = VendorMember.objects.create(
                    vendor=context.vendor, user=user, role=VendorMember.Role.EDITOR
                )
        except IntegrityError:
            return Response({"code": "MEMBER_EMAIL_CONFLICT"}, status=409)
        return Response(VendorMemberSerializer(member).data, status=201)


class VendorMediaListView(VendorAPIView):
    def get(self, request: Request) -> Response:
        context = self.context(request, roles=(VendorMember.Role.OWNER, VendorMember.Role.EDITOR))
        assets = context.scope(MediaAsset.objects).order_by("-created_at")
        return Response(MediaAssetSerializer(assets, many=True).data)


class VendorMemberDetailView(VendorAPIView):
    def delete(self, request: Request, member_id: uuid.UUID) -> Response:
        member = VendorMember.objects.filter(pk=member_id).select_related("vendor").first()
        if member is None:
            raise Http404
        self.context(request, vendor_id=member.vendor_id, roles=(VendorMember.Role.OWNER,))
        if member.user_id == request.user.id:
            return Response({"code": "CANNOT_REMOVE_SELF"}, status=409)
        member.delete()
        return Response(status=204)
