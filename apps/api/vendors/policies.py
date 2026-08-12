import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

from django.db import models
from django.http import Http404
from django.shortcuts import get_object_or_404

from accounts.models import User
from vendors.models import Vendor, VendorMember

ModelT = TypeVar("ModelT", bound=models.Model)


@dataclass(frozen=True, slots=True)
class VendorContext:
    vendor: Vendor
    membership: VendorMember | None

    @classmethod
    def resolve(
        cls,
        *,
        user: User,
        vendor_id: uuid.UUID,
        roles: Iterable[str] | None = None,
    ) -> "VendorContext":
        if not user.is_authenticated or not user.is_active or not vendor_id:
            raise Http404
        vendor = get_object_or_404(Vendor, pk=vendor_id, status=Vendor.Status.ACTIVE)
        if user.is_superuser:
            return cls(vendor=vendor, membership=None)
        if not user.is_email_verified:
            raise Http404
        memberships = VendorMember.objects.for_vendor(vendor_id).filter(user=user)
        if roles is not None:
            memberships = memberships.filter(role__in=tuple(roles))
        membership = memberships.first()
        if membership is None:
            raise Http404
        return cls(vendor=vendor, membership=membership)

    def scope(
        self, queryset: models.Manager[ModelT] | models.QuerySet[ModelT]
    ) -> models.QuerySet[ModelT]:
        return queryset.filter(vendor_id=self.vendor.id)

    def get_object_or_404(
        self, queryset: models.Manager[ModelT] | models.QuerySet[ModelT], **lookup: Any
    ) -> ModelT:
        return get_object_or_404(self.scope(queryset), **lookup)
