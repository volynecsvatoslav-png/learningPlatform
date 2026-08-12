from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse

from accounts.admin import backoffice_site
from media_assets.models import MediaAsset
from vendors.models import Vendor


@admin.register(MediaAsset, site=backoffice_site)
class MediaAssetAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("original_name", "vendor", "kind", "status", "created_at")
    list_filter = ("vendor", "status")
    search_fields = ("original_name",)
    readonly_fields = tuple(field.name for field in MediaAsset._meta.fields)
    change_list_template = "admin/media_assets/mediaasset/change_list.html"

    def get_queryset(self, request: HttpRequest) -> QuerySet[MediaAsset]:
        queryset = super().get_queryset(request).select_related("vendor", "created_by")
        if isinstance(request.user, AnonymousUser):
            return queryset.none()
        if request.user.is_superuser:
            return queryset
        return queryset.filter(vendor__members__user=request.user).distinct()

    def has_module_permission(self, request: HttpRequest) -> bool:
        if isinstance(request.user, AnonymousUser):
            return False
        return (
            request.user.is_superuser
            or request.user.vendor_memberships.filter(vendor__status=Vendor.Status.ACTIVE).exists()
        )

    def has_view_permission(self, request: HttpRequest, obj: MediaAsset | None = None) -> bool:
        if obj is None:
            return self.has_module_permission(request)
        visible = self.get_queryset(request)
        return visible.filter(pk=obj.pk).exists()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: MediaAsset | None = None) -> bool:
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: MediaAsset | None = None) -> bool:
        return False

    def get_urls(self):  # type: ignore[no-untyped-def]
        return [
            path(
                "upload/",
                self.admin_site.admin_view(self.upload_view),
                name="media_assets_mediaasset_upload",
            ),
            *super().get_urls(),
        ]

    def upload_view(self, request: HttpRequest) -> HttpResponse:
        if isinstance(request.user, AnonymousUser) or not self.has_module_permission(request):
            raise Http404
        vendors = (
            Vendor.objects.all()
            if request.user.is_superuser
            else Vendor.objects.filter(members__user=request.user, status=Vendor.Status.ACTIVE)
        )
        return TemplateResponse(
            request,
            "admin/media_assets/mediaasset/upload.html",
            {
                **self.admin_site.each_context(request),
                "title": "Загрузить медиа",
                "vendors": vendors,
                "create_url": reverse("media-upload-create"),
            },
        )
