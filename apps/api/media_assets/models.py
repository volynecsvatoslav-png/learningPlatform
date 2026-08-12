import uuid
from typing import Self

from django.conf import settings
from django.db import models

from vendors.models import TenantQuerySet, Vendor


class MediaAssetQuerySet(TenantQuerySet):
    def for_vendor(self, vendor_id: uuid.UUID) -> Self:
        return super().for_vendor(vendor_id)


class MediaAsset(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Изображение"
        VIDEO = "video", "Видео"
        AUDIO = "audio", "Аудио"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает загрузки"
        UPLOADED = "uploaded", "Загружен"
        VALIDATING = "validating", "Проверяется"
        READY = "ready", "Готов"
        REJECTED = "rejected", "Отклонён"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="media_assets")
    kind = models.CharField(max_length=8, choices=Kind)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    bucket = models.CharField(max_length=255)
    object_key = models.CharField(max_length=512, unique=True)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=127)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    duration_seconds = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=200, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_media_assets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MediaAssetQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("vendor", "status"), name="media_asset_vendor_status_idx")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0), name="media_asset_size_bytes_positive"
            )
        ]

    def __str__(self) -> str:
        return self.original_name
