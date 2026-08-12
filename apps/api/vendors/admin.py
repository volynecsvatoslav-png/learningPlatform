from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django.http import HttpRequest

from accounts.admin import backoffice_site
from vendors.models import Vendor, VendorMember


@admin.register(Vendor, site=backoffice_site)
class VendorAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "slug", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Vendor]:
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(members__user=request.user)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser

    def has_module_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser or self.get_queryset(request).exists()

    def has_view_permission(self, request: HttpRequest, obj: Vendor | None = None) -> bool:
        visible = self.get_queryset(request)
        return visible.exists() if obj is None else visible.filter(pk=obj.pk).exists()

    def has_change_permission(self, request: HttpRequest, obj: Vendor | None = None) -> bool:
        return request.user.is_superuser

    def has_delete_permission(self, request: HttpRequest, obj: Vendor | None = None) -> bool:
        return request.user.is_superuser


@admin.register(VendorMember, site=backoffice_site)
class VendorMemberAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "vendor", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("user__email", "vendor__name")
    autocomplete_fields = ("user", "vendor")

    def get_queryset(self, request: HttpRequest) -> QuerySet[VendorMember]:
        queryset = super().get_queryset(request).select_related("user", "vendor")
        if request.user.is_superuser:
            return queryset
        return queryset.filter(vendor__members__user=request.user).distinct()

    def _is_owner(self, request: HttpRequest, obj: VendorMember | None = None) -> bool:
        if isinstance(request.user, AnonymousUser):
            return False
        memberships = request.user.vendor_memberships.filter(role=VendorMember.Role.OWNER)
        if obj is not None:
            memberships = memberships.filter(vendor=obj.vendor)
        return bool(memberships.exists())

    def has_view_permission(self, request: HttpRequest, obj: VendorMember | None = None) -> bool:
        return request.user.is_superuser or self._is_owner(request, obj)

    def has_module_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser or self._is_owner(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser or self._is_owner(request)

    def has_change_permission(self, request: HttpRequest, obj: VendorMember | None = None) -> bool:
        return request.user.is_superuser or self._is_owner(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: VendorMember | None = None) -> bool:
        return request.user.is_superuser or self._is_owner(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):  # type: ignore[no-untyped-def]
        if not request.user.is_superuser and db_field.name == "vendor":
            kwargs["queryset"] = Vendor.objects.filter(
                members__user=request.user, members__role=VendorMember.Role.OWNER
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
