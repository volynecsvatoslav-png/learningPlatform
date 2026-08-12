import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from learning.validators import validate_markdown_without_html
from vendors.models import TenantQuerySet, Vendor


class CourseQuerySet(TenantQuerySet):
    def delete(self) -> tuple[int, dict[str, int]]:
        updated = self.update(status=Course.Status.ARCHIVED)
        return updated, {self.model._meta.label: updated}


class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликован"
        ARCHIVED = "archived", "Архив"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="courses")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100)
    short_description = models.TextField(blank=True)
    description_markdown = models.TextField(blank=True, validators=[validate_markdown_without_html])
    cover_asset = models.ForeignKey(
        "media_assets.MediaAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cover_for_courses",
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    offline_revision = models.PositiveIntegerField(default=1)
    current_revision = models.ForeignKey(
        "CourseRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_courses",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CourseQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("vendor", "slug"), name="learning_course_vendor_slug_unique"
            )
        ]
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title

    def archive(self) -> None:
        if self.status != self.Status.ARCHIVED:
            self.status = self.Status.ARCHIVED
            self.save(update_fields=("status", "updated_at"))

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        self.archive()
        return 0, {}


class CourseRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    snapshot_json = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="published_course_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("course", "revision_number"),
                name="learning_revision_course_number_unique",
            )
        ]
        ordering = ("course", "-revision_number")

    def __str__(self) -> str:
        return f"{self.course}: revision {self.revision_number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Published course revisions are immutable.")
        super().save(*args, **kwargs)


class CourseRevisionAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_revision = models.ForeignKey(
        CourseRevision, on_delete=models.CASCADE, related_name="revision_assets"
    )
    media_asset = models.ForeignKey(
        "media_assets.MediaAsset",
        on_delete=models.PROTECT,
        related_name="published_revisions",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("course_revision", "media_asset"),
                name="learning_revision_asset_unique",
            )
        ]


class Module(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("course", "position"), name="learning_module_course_position_unique"
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0), name="learning_module_position_positive"
            ),
        ]
        ordering = ("course", "position")

    def __str__(self) -> str:
        return self.title


class Lesson(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField()
    is_published = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("module", "position"), name="learning_lesson_module_position_unique"
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0), name="learning_lesson_position_positive"
            ),
        ]
        ordering = ("module", "position")

    def __str__(self) -> str:
        return self.title


class ContentUnit(models.Model):
    class Type(models.TextChoices):
        TEXT = "text", "Текст"
        VIDEO = "video", "Видео"
        AUDIO = "audio", "Аудио"
        IMAGE = "image", "Изображение"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="content_units")
    type = models.CharField(max_length=16, choices=Type)
    title = models.CharField(max_length=200, blank=True)
    position = models.PositiveIntegerField()
    text_markdown = models.TextField(
        null=True, blank=True, validators=[validate_markdown_without_html]
    )
    media_asset = models.ForeignKey(
        "media_assets.MediaAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="content_units",
    )
    is_downloadable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("lesson", "position"), name="learning_unit_lesson_position_unique"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        type="text",
                        text_markdown__isnull=False,
                        text_markdown__gt="",
                        media_asset__isnull=True,
                    )
                    | Q(
                        type__in=("video", "audio", "image"),
                        text_markdown__isnull=True,
                        media_asset__isnull=False,
                    )
                ),
                name="learning_unit_content_matches_type",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0), name="learning_unit_position_positive"
            ),
        ]
        ordering = ("lesson", "position")

    def __str__(self) -> str:
        return self.title or self.get_type_display()

    def clean(self) -> None:
        super().clean()
        if self.type == self.Type.TEXT:
            if not self.text_markdown or not self.text_markdown.strip():
                raise ValidationError({"text_markdown": "Text content requires Markdown."})
            if self.media_asset_id:
                raise ValidationError({"media_asset": "Text content cannot have media."})
        elif self.type in {self.Type.VIDEO, self.Type.AUDIO, self.Type.IMAGE}:
            if self.text_markdown is not None:
                raise ValidationError({"text_markdown": "Media content cannot have Markdown."})
            if not self.media_asset_id:
                raise ValidationError({"media_asset": "Media content requires an asset."})
