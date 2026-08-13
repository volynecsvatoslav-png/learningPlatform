import os

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email, validate_slug
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from accounts.models import User
from vendors.models import Vendor, VendorMember


class Command(BaseCommand):
    help = "Create the single vendor owner required by end-to-end tests on an empty database."

    def handle(self, *args: object, **options: object) -> None:
        if not settings.DEBUG or os.getenv("E2E_BOOTSTRAP_ENABLED") != "true":
            raise CommandError("E2E bootstrap requires DEBUG and E2E_BOOTSTRAP_ENABLED=true.")

        values = self._environment()
        email = User.objects.normalize_email_address(values["E2E_OWNER_EMAIL"])
        password = values["E2E_OWNER_PASSWORD"]
        vendor_name = values["E2E_VENDOR_NAME"].strip()
        vendor_slug = values["E2E_VENDOR_SLUG"].strip()
        self._validate(email, password, vendor_name, vendor_slug)

        try:
            with transaction.atomic():
                self._lock_bootstrap()
                users = list(User.objects.select_for_update().all())
                vendors = list(Vendor.objects.select_for_update().all())
                memberships = list(VendorMember.objects.select_for_update().all())

                if not users and not vendors and not memberships:
                    vendor = Vendor.objects.create(
                        name=vendor_name,
                        slug=vendor_slug,
                        status=Vendor.Status.ACTIVE,
                    )
                    user = User.objects.create_user(
                        email,
                        password,
                        email_verified_at=timezone.now(),
                        is_active=True,
                        is_staff=False,
                        is_superuser=False,
                    )
                    VendorMember.objects.create(
                        vendor=vendor,
                        user=user,
                        role=VendorMember.Role.OWNER,
                    )
                    created = True
                elif self._is_exact_tuple(
                    users,
                    vendors,
                    memberships,
                    email=email,
                    password=password,
                    vendor_name=vendor_name,
                    vendor_slug=vendor_slug,
                ):
                    created = False
                else:
                    raise CommandError(
                        "E2E bootstrap refused: the database does not contain the exact "
                        "requested tuple."
                    )
        except IntegrityError as error:
            raise CommandError(
                "E2E bootstrap refused because the requested tuple conflicts."
            ) from error

        action = "created" if created else "already exists"
        self.stdout.write(self.style.SUCCESS(f"E2E owner tuple {action} for {email}."))

    @staticmethod
    def _environment() -> dict[str, str]:
        names = (
            "E2E_OWNER_EMAIL",
            "E2E_OWNER_PASSWORD",
            "E2E_VENDOR_NAME",
            "E2E_VENDOR_SLUG",
        )
        values = {name: os.getenv(name, "") for name in names}
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise CommandError(f"Missing required environment variables: {', '.join(missing)}.")
        return values

    @staticmethod
    def _validate(email: str, password: str, vendor_name: str, vendor_slug: str) -> None:
        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError("E2E_OWNER_EMAIL is invalid.") from error
        if not vendor_name or len(vendor_name) > 200:
            raise CommandError("E2E_VENDOR_NAME is invalid.")
        try:
            validate_slug(vendor_slug)
        except ValidationError as error:
            raise CommandError("E2E_VENDOR_SLUG is invalid.") from error
        if len(vendor_slug) > 100:
            raise CommandError("E2E_VENDOR_SLUG is invalid.")
        try:
            validate_password(password, user=User(email=email))
        except ValidationError as error:
            raise CommandError("E2E_OWNER_PASSWORD is invalid.") from error

    @staticmethod
    def _lock_bootstrap() -> None:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [1162162757])

    @staticmethod
    def _is_exact_tuple(
        users: list[User],
        vendors: list[Vendor],
        memberships: list[VendorMember],
        *,
        email: str,
        password: str,
        vendor_name: str,
        vendor_slug: str,
    ) -> bool:
        if len(users) != 1 or len(vendors) != 1 or len(memberships) != 1:
            return False
        user, vendor, membership = users[0], vendors[0], memberships[0]
        return (
            user.email == email
            and user.check_password(password)
            and user.email_verified_at is not None
            and user.is_active
            and not user.is_staff
            and not user.is_superuser
            and not user.groups.exists()
            and not user.user_permissions.exists()
            and vendor.name == vendor_name
            and vendor.slug == vendor_slug
            and vendor.status == Vendor.Status.ACTIVE
            and membership.user_id == user.id
            and membership.vendor_id == vendor.id
            and membership.role == VendorMember.Role.OWNER
        )
