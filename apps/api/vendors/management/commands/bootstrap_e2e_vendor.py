import os

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email, validate_slug
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from learning.models import ContentUnit, Course, Lesson, Module
from learning.services import publish_course
from vendors.models import Vendor, VendorMember


class Command(BaseCommand):
    help = (
        "Create the second vendor required by end-to-end tenant isolation tests. "
        "Idempotent: objects are reused when the exact tuple already exists."
    )

    def handle(self, *args: object, **options: object) -> None:
        if not settings.DEBUG or os.getenv("E2E_BOOTSTRAP_ENABLED") != "true":
            raise CommandError("E2E bootstrap requires DEBUG and E2E_BOOTSTRAP_ENABLED=true.")

        values = self._environment()
        owner_email = User.objects.normalize_email_address(values["E2E_VENDOR_B_OWNER_EMAIL"])
        password = values["E2E_VENDOR_B_OWNER_PASSWORD"]
        vendor_name = values["E2E_VENDOR_B_NAME"].strip()
        vendor_slug = values["E2E_VENDOR_B_SLUG"].strip()
        course_title = values["E2E_VENDOR_B_COURSE_TITLE"].strip()
        course_slug = values["E2E_VENDOR_B_COURSE_SLUG"].strip()
        self._validate(owner_email, password, vendor_name, vendor_slug, course_title, course_slug)

        created = False
        try:
            with transaction.atomic():
                vendor = Vendor.objects.filter(slug=vendor_slug).first()
                owner = User.objects.filter(email=owner_email).first()
                if vendor is None and owner is None:
                    vendor = Vendor.objects.create(
                        name=vendor_name,
                        slug=vendor_slug,
                        status=Vendor.Status.ACTIVE,
                    )
                    owner = User.objects.create_user(
                        owner_email,
                        password,
                        email_verified_at=timezone.now(),
                        is_active=True,
                        is_staff=False,
                        is_superuser=False,
                    )
                    VendorMember.objects.create(
                        vendor=vendor,
                        user=owner,
                        role=VendorMember.Role.OWNER,
                    )
                elif vendor is None or owner is None:
                    raise CommandError(
                        "E2E vendor B bootstrap refused: vendor and owner must be created together."
                    )
                if vendor.slug != vendor_slug or owner.email != owner_email:
                    raise CommandError(
                        "E2E vendor B bootstrap refused: slug or owner email mismatch."
                    )
                if not owner.check_password(password):
                    raise CommandError(
                        "E2E vendor B bootstrap refused: owner password does not match."
                    )

                course = Course.objects.filter(vendor=vendor, slug=course_slug).first()
                if course is None:
                    created = True
                    course = Course.objects.create(
                        vendor=vendor,
                        title=course_title,
                        slug=course_slug,
                        short_description=f"Tenant isolation fixture {course_slug}",
                        description_markdown=f"# {course_title}",
                    )
                    module = Module.objects.create(course=course, title="Module", position=1)
                    lesson = Lesson.objects.create(
                        module=module, title="Lesson", position=1, is_published=True
                    )
                    ContentUnit.objects.create(
                        lesson=lesson,
                        type=ContentUnit.Type.TEXT,
                        position=1,
                        text_markdown=f"# {course_title}",
                    )
                    course.status = Course.Status.PUBLISHED
                    publish_course(course)
        except IntegrityError as error:
            raise CommandError(
                "E2E vendor B bootstrap refused because the tuple conflicts."
            ) from error

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"E2E vendor B bootstrap complete: {vendor_slug}.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"E2E vendor B tuple already exists for {vendor_slug}; nothing to create."
                )
            )

    @staticmethod
    def _environment() -> dict[str, str]:
        names = (
            "E2E_VENDOR_B_NAME",
            "E2E_VENDOR_B_SLUG",
            "E2E_VENDOR_B_OWNER_EMAIL",
            "E2E_VENDOR_B_OWNER_PASSWORD",
            "E2E_VENDOR_B_COURSE_TITLE",
            "E2E_VENDOR_B_COURSE_SLUG",
        )
        values = {name: os.getenv(name, "") for name in names}
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise CommandError(f"Missing required environment variables: {', '.join(missing)}.")
        return values

    @staticmethod
    def _validate(
        owner_email: str,
        password: str,
        vendor_name: str,
        vendor_slug: str,
        course_title: str,
        course_slug: str,
    ) -> None:
        try:
            validate_email(owner_email)
        except ValidationError as error:
            raise CommandError("E2E_VENDOR_B_OWNER_EMAIL is invalid.") from error
        if not vendor_name or len(vendor_name) > 200:
            raise CommandError("E2E_VENDOR_B_NAME is invalid.")
        if not course_title or len(course_title) > 200:
            raise CommandError("E2E_VENDOR_B_COURSE_TITLE is invalid.")
        try:
            validate_slug(vendor_slug)
            validate_slug(course_slug)
        except ValidationError as error:
            raise CommandError(
                "E2E_VENDOR_B_SLUG or E2E_VENDOR_B_COURSE_SLUG is invalid."
            ) from error
        if len(vendor_slug) > 100 or len(course_slug) > 100:
            raise CommandError("E2E_VENDOR_B_SLUG or E2E_VENDOR_B_COURSE_SLUG is invalid.")
        try:
            validate_password(password, user=User(email=owner_email))
        except ValidationError as error:
            raise CommandError("E2E_VENDOR_B_OWNER_PASSWORD is invalid.") from error
