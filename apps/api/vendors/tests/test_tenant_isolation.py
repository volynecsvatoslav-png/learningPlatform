import pytest
from django.http import Http404, HttpRequest
from django.test import Client
from django.utils import timezone

from accounts.admin import backoffice_site
from accounts.models import User
from vendors.admin import VendorAdmin, VendorMemberAdmin
from vendors.models import Vendor, VendorMember
from vendors.policies import VendorContext

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery staple"


def owner(email: str, vendor: Vendor) -> User:
    user = User.objects.create_user(
        email, PASSWORD, is_staff=True, email_verified_at=timezone.now()
    )
    VendorMember.objects.create(vendor=vendor, user=user, role=VendorMember.Role.OWNER)
    return user


def test_policy_returns_404_for_other_vendor() -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    alpha_owner = owner("alpha@example.com", alpha)
    owner("beta@example.com", beta)

    assert VendorContext.resolve(user=alpha_owner, vendor_id=alpha.id).vendor == alpha
    with pytest.raises(Http404):
        VendorContext.resolve(user=alpha_owner, vendor_id=beta.id)


def test_two_owners_only_see_their_members_and_cross_tenant_url_is_denied(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    alpha_owner = owner("alpha@example.com", alpha)
    beta_owner = owner("beta@example.com", beta)
    beta_membership = beta_owner.vendor_memberships.get()
    request = HttpRequest()
    request.user = alpha_owner
    admin = VendorMemberAdmin(VendorMember, backoffice_site)
    vendor_admin = VendorAdmin(Vendor, backoffice_site)

    assert list(admin.get_queryset(request)) == [alpha_owner.vendor_memberships.get()]
    assert not admin.has_view_permission(request, beta_membership)
    assert vendor_admin.has_view_permission(request, alpha)
    assert not vendor_admin.has_view_permission(request, beta)
    assert admin.has_module_permission(request)

    client.force_login(alpha_owner)
    response = client.get(f"/backoffice/vendors/vendormember/{beta_membership.pk}/change/")
    assert response.status_code in {302, 403, 404}
