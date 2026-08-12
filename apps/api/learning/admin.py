from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.contrib.auth.models import AnonymousUser
from django.db import models
from django.db.models import Count, QuerySet
from django.forms import ModelChoiceField
from django.http import Http404, HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from accounts.admin import backoffice_site
from learning.models import ContentUnit, Course, CourseRevision, CourseRevisionAsset, Lesson, Module
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
from vendors.models import Vendor


class CourseWithModuleCount:
    _module_count: int


class TenantLearningAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    tenant_lookup = "vendor"

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        queryset = super().get_queryset(request)
        if isinstance(request.user, AnonymousUser):
            return queryset.none()
        if request.user.is_superuser:
            return queryset
        return queryset.filter(**{f"{self.tenant_lookup}__members__user": request.user}).distinct()

    def _can_manage_any_course(self, request: HttpRequest) -> bool:
        return bool(
            not isinstance(request.user, AnonymousUser)
            and request.user.vendor_memberships.filter(vendor__status=Vendor.Status.ACTIVE).exists()
        )

    def has_module_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser or self._can_manage_any_course(request)

    def has_view_permission(self, request: HttpRequest, obj=None) -> bool:  # type: ignore[no-untyped-def]
        if obj is None:
            return self.has_module_permission(request)
        return self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser or self._can_manage_any_course(request)

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return self.has_view_permission(request, obj)

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        if object_id and self.get_object(request, object_id) is None:
            raise Http404
        return super().changeform_view(request, object_id, form_url, extra_context)

    def delete_view(
        self,
        request: HttpRequest,
        object_id: str,
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        if self.get_object(request, object_id) is None:
            raise Http404
        return super().delete_view(request, object_id, extra_context)

    def history_view(
        self,
        request: HttpRequest,
        object_id: str,
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        if self.get_object(request, object_id) is None:
            raise Http404
        return super().history_view(request, object_id, extra_context)

    def formfield_for_foreignkey(
        self, db_field: models.ForeignKey[Any, Any], request: HttpRequest, **kwargs: Any
    ) -> ModelChoiceField[Any] | None:
        if isinstance(request.user, AnonymousUser):
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        if request.user.is_superuser:
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        vendor_ids = request.user.vendor_memberships.filter(
            vendor__status=Vendor.Status.ACTIVE
        ).values("vendor_id")
        fields = {
            "vendor": Vendor.objects.filter(pk__in=vendor_ids),
            "course": Course.objects.filter(vendor_id__in=vendor_ids),
            "module": Module.objects.filter(course__vendor_id__in=vendor_ids),
            "lesson": Lesson.objects.filter(module__course__vendor_id__in=vendor_ids),
            "course_revision": CourseRevision.objects.filter(course__vendor_id__in=vendor_ids),
            "cover_asset": MediaAsset.objects.filter(vendor_id__in=vendor_ids),
            "media_asset": MediaAsset.objects.filter(vendor_id__in=vendor_ids),
        }
        if db_field.name in fields:
            kwargs["queryset"] = fields[db_field.name]
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Course, site=backoffice_site)
class CourseAdmin(TenantLearningAdmin):
    list_display = ("title", "vendor", "status", "module_count", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "slug")
    readonly_fields = (
        "offline_revision",
        "current_revision",
        "published_at",
        "created_at",
        "updated_at",
        "modules_link",
        "published_preview_link",
    )
    actions = ("publish_selected", "archive_selected")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Course]:
        return cast(
            QuerySet[Course], super().get_queryset(request).annotate(_module_count=Count("modules"))
        )

    @admin.display(description="Модули", ordering="_module_count")
    def module_count(self, obj: Course) -> int:
        return cast(CourseWithModuleCount, obj)._module_count

    @admin.display(description="Структура")
    def modules_link(self, obj: Course) -> str:
        url = reverse("backoffice:learning_module_changelist")
        return format_html(
            '<a href="{}?{}">Управлять модулями</a>', url, urlencode({"course__id__exact": obj.pk})
        )

    @admin.display(description="Предпросмотр")
    def published_preview_link(self, obj: Course) -> str:
        if obj.current_revision_id is None:
            return "Опубликованной версии нет"
        url = reverse("backoffice:learning_course_preview", args=(obj.pk,))
        return format_html('<a href="{}" target="_blank">Открыть опубликованную версию</a>', url)

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<uuid:course_id>/preview/",
                self.admin_site.admin_view(self.preview_view),
                name="learning_course_preview",
            ),
            *super().get_urls(),
        ]

    def preview_view(self, request: HttpRequest, course_id: str) -> HttpResponse:
        course = self.get_queryset(request).filter(pk=course_id).first()
        if course is None or course.current_revision is None:
            raise Http404
        return TemplateResponse(
            request,
            "admin/learning/course/preview.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Предпросмотр: {course.title}",
                "snapshot": course.current_revision.snapshot_json,
                "opts": self.model._meta,
                "original": course,
            },
        )

    @admin.action(description="Опубликовать выбранные курсы")
    def publish_selected(self, request: HttpRequest, queryset: QuerySet[Course]) -> None:
        for course in queryset:
            try:
                publish_course(course, created_by=request.user)
            except PublicationValidationError as error:
                self.message_user(request, f"{course}: {error}", messages.ERROR)
            else:
                self.message_user(request, f"{course}: опубликован.", messages.SUCCESS)

    @admin.action(description="Архивировать выбранные курсы")
    def archive_selected(self, request: HttpRequest, queryset: QuerySet[Course]) -> None:
        queryset.update(status=Course.Status.ARCHIVED)

    def delete_model(self, request: HttpRequest, obj: Course) -> None:
        obj.archive()

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[Course]) -> None:
        queryset.update(status=Course.Status.ARCHIVED)


@admin.register(Module, site=backoffice_site)
class ModuleAdmin(TenantLearningAdmin):
    tenant_lookup = "course__vendor"
    list_display = ("title", "course", "position", "lessons_link")
    search_fields = ("title", "course__title")
    list_filter = ("course",)

    def get_readonly_fields(
        self, request: HttpRequest, obj: Module | None = None
    ) -> tuple[str, ...]:
        return ("course",) if obj else ()

    def save_model(self, request: HttpRequest, obj: Module, form, change: bool) -> None:  # type: ignore[no-untyped-def]
        desired_position = obj.position
        if change:
            obj.position = Module.objects.only("position").get(pk=obj.pk).position
            super().save_model(request, obj, form, change)
            move_module(obj, desired_position)
            return
        created = create_module(
            obj.course, position=desired_position, title=obj.title, description=obj.description
        )
        obj.pk = created.pk

    def delete_model(self, request: HttpRequest, obj: Module) -> None:
        delete_module(obj)

    @admin.display(description="Уроки")
    def lessons_link(self, obj: Module) -> str:
        url = reverse("backoffice:learning_lesson_changelist")
        return format_html(
            '<a href="{}?{}">Управлять уроками</a>', url, urlencode({"module__id__exact": obj.pk})
        )


@admin.register(Lesson, site=backoffice_site)
class LessonAdmin(TenantLearningAdmin):
    tenant_lookup = "module__course__vendor"
    list_display = ("title", "module", "position", "is_published", "units_link")
    search_fields = ("title", "module__title")
    list_filter = ("is_published", "module")

    def get_readonly_fields(
        self, request: HttpRequest, obj: Lesson | None = None
    ) -> tuple[str, ...]:
        return ("module",) if obj else ()

    def save_model(self, request: HttpRequest, obj: Lesson, form, change: bool) -> None:  # type: ignore[no-untyped-def]
        desired_position = obj.position
        if change:
            obj.position = Lesson.objects.only("position").get(pk=obj.pk).position
            super().save_model(request, obj, form, change)
            move_lesson(obj, desired_position)
            return
        created = create_lesson(
            obj.module,
            position=desired_position,
            title=obj.title,
            description=obj.description,
            is_published=obj.is_published,
        )
        obj.pk = created.pk

    def delete_model(self, request: HttpRequest, obj: Lesson) -> None:
        delete_lesson(obj)

    @admin.display(description="Контент")
    def units_link(self, obj: Lesson) -> str:
        url = reverse("backoffice:learning_contentunit_changelist")
        return format_html(
            '<a href="{}?{}">Управлять контентом</a>', url, urlencode({"lesson__id__exact": obj.pk})
        )


@admin.register(ContentUnit, site=backoffice_site)
class ContentUnitAdmin(TenantLearningAdmin):
    tenant_lookup = "lesson__module__course__vendor"
    list_display = ("title", "type", "lesson", "position", "is_downloadable")
    search_fields = ("title", "lesson__title")
    list_filter = ("type", "is_downloadable")

    def get_readonly_fields(
        self, request: HttpRequest, obj: ContentUnit | None = None
    ) -> tuple[str, ...]:
        return ("lesson",) if obj else ()

    def save_model(self, request: HttpRequest, obj: ContentUnit, form, change: bool) -> None:  # type: ignore[no-untyped-def]
        desired_position = obj.position
        if change:
            obj.position = ContentUnit.objects.only("position").get(pk=obj.pk).position
            super().save_model(request, obj, form, change)
            move_content_unit(obj, desired_position)
            return
        created = create_content_unit(
            obj.lesson,
            position=desired_position,
            type=obj.type,
            title=obj.title,
            text_markdown=obj.text_markdown,
            media_asset=obj.media_asset,
            is_downloadable=obj.is_downloadable,
        )
        obj.pk = created.pk

    def delete_model(self, request: HttpRequest, obj: ContentUnit) -> None:
        delete_content_unit(obj)


@admin.register(CourseRevision, site=backoffice_site)
class CourseRevisionAdmin(TenantLearningAdmin):
    tenant_lookup = "course__vendor"
    list_display = ("course", "revision_number", "snapshot_sha256", "created_at")
    readonly_fields = (
        "course",
        "revision_number",
        "snapshot_json",
        "snapshot_sha256",
        "created_by",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False


@admin.register(CourseRevisionAsset, site=backoffice_site)
class CourseRevisionAssetAdmin(TenantLearningAdmin):
    tenant_lookup = "course_revision__course__vendor"
    list_display = ("course_revision", "media_asset")
    readonly_fields = ("course_revision", "media_asset")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False
