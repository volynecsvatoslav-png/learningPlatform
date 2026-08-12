from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django.http import HttpRequest

from accounts.forms import BackofficeUserChangeForm, BackofficeUserCreationForm
from accounts.models import User


class BackofficeAdminSite(admin.AdminSite):
    site_header = "Учебная платформа"
    site_title = "Бэк-офис"
    index_title = "Управление платформой"

    def has_permission(self, request: HttpRequest) -> bool:
        user = request.user
        if not user.is_active or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return bool(
            getattr(user, "email_verified_at", None)
            and user.vendor_memberships.filter(vendor__status="active").exists()
        )


backoffice_site = BackofficeAdminSite(name="backoffice")


@admin.register(User, site=backoffice_site)
class BackofficeUserAdmin(UserAdmin):  # type: ignore[type-arg]
    add_form = BackofficeUserCreationForm
    form = BackofficeUserChangeForm
    model = User
    ordering = ("email",)
    list_display = ("email", "email_verified_at", "is_active", "is_superuser")
    search_fields = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Статус", {"fields": ("email_verified_at", "is_active", "is_staff")}),
        ("Права платформы", {"fields": ("is_superuser", "groups", "user_permissions")}),
        ("Даты", {"fields": ("last_login_at", "last_login", "created_at", "updated_at")}),
    )
    readonly_fields = ("last_login", "created_at", "updated_at")
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "email_verified_at", "is_active"),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[User]:
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(vendor_memberships__vendor__members__user=request.user).distinct()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser

    def has_module_permission(self, request: HttpRequest) -> bool:
        if isinstance(request.user, AnonymousUser):
            return False
        return (
            request.user.is_superuser
            or request.user.vendor_memberships.filter(
                role="owner", vendor__status="active"
            ).exists()
        )

    def has_view_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        if request.user.is_superuser:
            return True
        visible: QuerySet[User] = self.get_queryset(request)
        return visible.exists() if obj is None else visible.filter(pk=obj.pk).exists()

    def has_change_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        return request.user.is_superuser

    def has_delete_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        return request.user.is_superuser
