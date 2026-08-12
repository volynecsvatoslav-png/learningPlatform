from django.contrib import admin

from learner.models import AccessLink, Enrollment


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("learner", "course", "status", "granted_at", "revoked_at")
    list_filter = ("status",)
    search_fields = ("learner__email", "course__title")


@admin.register(AccessLink)
class AccessLinkAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("enrollment", "created_at", "revoked_at")
    readonly_fields = tuple(field.name for field in AccessLink._meta.fields)
