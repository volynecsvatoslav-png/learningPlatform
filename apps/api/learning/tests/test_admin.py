import pytest
from django.http import HttpRequest
from django.test import Client
from django.utils import timezone

from accounts.admin import backoffice_site
from accounts.models import User
from learning.admin import ContentUnitAdmin, CourseAdmin, LessonAdmin, ModuleAdmin
from learning.models import ContentUnit, Course, Lesson, Module
from vendors.models import Vendor, VendorMember

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery staple"


def make_editor(email: str, vendor: Vendor) -> User:
    user = User.objects.create_user(
        email, PASSWORD, is_staff=True, email_verified_at=timezone.now()
    )
    VendorMember.objects.create(vendor=vendor, user=user, role=VendorMember.Role.EDITOR)
    return user


def make_course(vendor: Vendor) -> tuple[Course, Module, Lesson, ContentUnit]:
    course = Course.objects.create(vendor=vendor, title="Course", slug=f"course-{vendor.slug}")
    module = Module.objects.create(course=course, title="Module", position=1)
    lesson = Lesson.objects.create(module=module, title="Lesson", position=1)
    unit = ContentUnit.objects.create(
        lesson=lesson, type=ContentUnit.Type.TEXT, position=1, text_markdown="Safe"
    )
    return course, module, lesson, unit


def test_editor_sees_only_own_learning_tree_and_direct_foreign_url_is_404(client: Client) -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    editor = make_editor("editor@example.com", alpha)
    alpha_tree = make_course(alpha)
    beta_tree = make_course(beta)
    request = HttpRequest()
    request.user = editor

    assert list(CourseAdmin(Course, backoffice_site).get_queryset(request)) == [alpha_tree[0]]
    assert list(ModuleAdmin(Module, backoffice_site).get_queryset(request)) == [alpha_tree[1]]
    assert list(LessonAdmin(Lesson, backoffice_site).get_queryset(request)) == [alpha_tree[2]]
    assert list(ContentUnitAdmin(ContentUnit, backoffice_site).get_queryset(request)) == [
        alpha_tree[3]
    ]
    client.force_login(editor)
    response = client.get(f"/backoffice/learning/course/{beta_tree[0].pk}/change/")
    assert response.status_code == 404
    response = client.get(f"/backoffice/learning/course/{beta_tree[0].pk}/delete/")
    assert response.status_code == 404


def test_platform_superuser_sees_all_courses() -> None:
    alpha = Vendor.objects.create(name="Alpha", slug="alpha")
    beta = Vendor.objects.create(name="Beta", slug="beta")
    alpha_course, *_ = make_course(alpha)
    beta_course, *_ = make_course(beta)
    admin_user = User.objects.create_superuser("admin@example.com", PASSWORD)
    request = HttpRequest()
    request.user = admin_user

    assert set(CourseAdmin(Course, backoffice_site).get_queryset(request)) == {
        alpha_course,
        beta_course,
    }
