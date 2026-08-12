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


class LearnerSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="learner_sessions")
    session_key = models.CharField(max_length=40, unique=True)
    device_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class LessonProgress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="lesson_progress")
    lesson_id = models.UUIDField()
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lesson_progress")
    percent = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=16, default="in_progress")
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("learner", "lesson_id"), name="learner_progress_learner_lesson_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(percent__gte=0, percent__lte=100),
                name="learner_progress_percent_range",
            ),
        ]
