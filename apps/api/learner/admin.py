from django.contrib import admin

from learner.models import (
    AccessLink,
    AccessPass,
    Device,
    Enrollment,
    LearnerSession,
    OfflineLicense,
    RecoveryChallenge,
)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "vendor", "course", "status", "granted_at", "revoked_at")
    list_filter = ("status", "source")
    search_fields = ("user__email", "course__title")


@admin.register(AccessPass)
class AccessPassAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("vendor", "user", "token_prefix", "generation", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("token_prefix", "user__email", "vendor__name")
    readonly_fields = tuple(field.name for field in AccessPass._meta.fields)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("access_pass", "installation_id", "display_name", "first_seen_at", "revoked_at")
    list_filter = ("revoked_at",)
    readonly_fields = tuple(field.name for field in Device._meta.fields)


@admin.register(LearnerSession)
class LearnerSessionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("learner", "access_pass", "device", "pass_generation", "revoked_at")
    list_filter = ("revoke_reason",)
    readonly_fields = tuple(field.name for field in LearnerSession._meta.fields)


@admin.register(OfflineLicense)
class OfflineLicenseAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("device", "course", "pass_generation", "issued_at", "expires_at")
    readonly_fields = tuple(field.name for field in OfflineLicense._meta.fields)


@admin.register(RecoveryChallenge)
class RecoveryChallengeAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "vendor", "created_at", "expires_at", "used_at")
    readonly_fields = tuple(field.name for field in RecoveryChallenge._meta.fields)


@admin.register(AccessLink)
class AccessLinkAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("enrollment", "created_at", "revoked_at")
    readonly_fields = tuple(field.name for field in AccessLink._meta.fields)
