import hashlib
import hmac
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import User
from learning.models import Course
from vendors.models import Vendor


def hash_access_token(token: str) -> str:
    return hmac.new(
        settings.ACCESS_TOKEN_PEPPER.encode(), token.encode(), hashlib.sha256
    ).hexdigest()


def hash_recovery_token(token: str) -> str:
    return hmac.new(
        settings.ACCESS_TOKEN_PEPPER.encode(), token.encode(), hashlib.sha256
    ).hexdigest()


def hash_session_token(session_key: str) -> str:
    return hmac.new(
        settings.SESSION_TOKEN_PEPPER.encode(), session_key.encode(), hashlib.sha256
    ).hexdigest()


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        REVOKED = "revoked", "Отозван"
        EXPIRED = "expired", "Истёк"

    class Source(models.TextChoices):
        MANUAL = "manual", "Вручную"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="enrollments")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrollments")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    source = models.CharField(max_length=16, choices=Source, default=Source.MANUAL)
    source_reference = models.CharField(max_length=255, null=True, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
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
            models.UniqueConstraint(fields=("user", "course"), name="learner_enrollment_unique"),
        ]
        ordering = ("-granted_at",)

    def clean(self) -> None:
        super().clean()
        if self.course_id and self.vendor_id and self.vendor_id != self.course.vendor_id:
            raise ValidationError("Enrollment vendor must match the course vendor.")


class AccessPass(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        REVOKED = "revoked", "Отозван"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="access_passes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="access_passes")
    token_hash = models.CharField(max_length=64, unique=True)
    token_prefix = models.CharField(max_length=12)
    generation = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("vendor", "user"),
                condition=models.Q(status="active"),
                name="access_pass_one_active_per_user_vendor",
            )
        ]
        ordering = ("-created_at",)


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    access_pass = models.ForeignKey(AccessPass, on_delete=models.CASCADE, related_name="devices")
    installation_id = models.UUIDField(db_index=True)
    public_key_jwk = models.JSONField()
    public_key_fingerprint = models.CharField(max_length=64, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, default="")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-first_seen_at",)


class DeviceChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    access_pass = models.ForeignKey(AccessPass, on_delete=models.CASCADE, related_name="challenges")
    challenge = models.CharField(max_length=43)
    installation_id = models.UUIDField()
    public_key_jwk = models.JSONField()
    public_key_fingerprint = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("access_pass", "used_at", "expires_at"),
                name="device_challenge_active_idx",
            )
        ]


class RecoveryChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_challenges")
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="recovery_challenges")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    requested_ip_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("user", "used_at", "expires_at"),
                name="recovery_challenge_active_idx",
            )
        ]


class LearnerSession(models.Model):
    class RevokeReason(models.TextChoices):
        REPLACED = "replaced", "Заменена"
        MANUAL = "manual", "Вручную"
        LOGOUT = "logout", "Выход"
        EXPIRED = "expired", "Истекла"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="learner_sessions")
    access_pass = models.ForeignKey(
        AccessPass,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    device = models.ForeignKey(
        Device,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    session_key = models.CharField(max_length=40, unique=True)
    session_token_hash = models.CharField(max_length=64, default="", db_index=True)
    device_hash = models.CharField(max_length=64)
    pass_generation = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(
        max_length=16, choices=RevokeReason.choices, null=True, blank=True
    )

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("access_pass",),
                condition=models.Q(revoked_at__isnull=True),
                name="learner_session_one_active_per_pass",
            )
        ]


class OfflineLicense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="offline_licenses")
    access_pass = models.ForeignKey(
        AccessPass, on_delete=models.CASCADE, related_name="offline_licenses"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="offline_licenses")
    course_revision = models.ForeignKey(
        "learning.CourseRevision",
        on_delete=models.CASCADE,
        related_name="offline_licenses",
    )
    pass_generation = models.PositiveIntegerField()
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-issued_at",)


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
