import hashlib
import hmac
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import User
from learning.models import Course


def hash_access_token(token: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        REVOKED = "revoked", "Отозван"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrollments")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_enrollments",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("learner", "course"), name="learner_enrollment_unique")
        ]
        ordering = ("-granted_at",)


class AccessLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="access_links"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
