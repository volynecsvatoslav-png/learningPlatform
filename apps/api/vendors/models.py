import uuid
from typing import Any, Self

from django.conf import settings
from django.db import models


class TenantQuerySet(models.QuerySet[Any]):
    def for_vendor(self, vendor_id: uuid.UUID) -> Self:
        if not vendor_id:
            raise ValueError("An explicit vendor_id is required")
        return self.filter(vendor_id=vendor_id)


class Vendor(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        SUSPENDED = "suspended", "Приостановлен"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class VendorMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Владелец"
        EDITOR = "editor", "Редактор"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vendor_memberships"
    )
    role = models.CharField(max_length=16, choices=Role)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("vendor", "user"), name="vendors_member_vendor_user_unique"
            )
        ]
        ordering = ("vendor__name", "user__email")

    def __str__(self) -> str:
        return f"{self.user} - {self.vendor} ({self.get_role_display()})"
