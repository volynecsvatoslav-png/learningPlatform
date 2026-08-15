import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from accounts.models import User
from learning.models import ContentUnit, Course, CourseRevisionAsset, Lesson, Module
from learning.services import (
    PublicationValidationError,
    create_content_unit,
    create_lesson,
    create_module,
    delete_content_unit,
    delete_module,
    move_content_unit,
    move_module,
    publish_course,
)
from media_assets.models import MediaAsset
from vendors.models import Vendor

pytestmark = pytest.mark.django_db


def make_course() -> tuple[Vendor, Course, User]:
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    user = User.objects.create_user("author@example.com", "correct horse battery staple")
    return vendor, Course.objects.create(vendor=vendor, title="Course", slug="course"), user


def make_asset(
    vendor: Vendor, user: User, *, kind: str = "video", status: str = "ready"
) -> MediaAsset:
    return MediaAsset.objects.create(
        vendor=vendor,
        kind=kind,
        status=status,
        bucket="learning-platform",
        object_key=f"vendors/{vendor.id}/assets/{kind}-{status}/source",
        original_name={"image": "cover.png", "audio": "track.mp3", "video": "clip.mp4"}[kind],
        content_type={"image": "image/png", "audio": "audio/mpeg", "video": "video/mp4"}[kind],
        size_bytes=4,
        sha256="0" * 64,
        created_by=user,
    )


def make_published_tree(course: Course, asset: MediaAsset | None = None) -> tuple[Module, Lesson]:
    module = create_module(course, title="Module", description="")
    lesson = create_lesson(module, title="Lesson", description="", is_published=True)
    if asset:
        create_content_unit(
            lesson,
            type=ContentUnit.Type.VIDEO,
            media_asset=asset,
        )
    else:
        create_content_unit(lesson, type=ContentUnit.Type.TEXT, text_markdown="# Safe")
    return module, lesson


def test_content_unit_disables_offline_access_by_default() -> None:
    _, course, _ = make_course()
    module = create_module(course, title="Module")
    lesson = create_lesson(module, title="Lesson")

    unit = create_content_unit(
        lesson, type=ContentUnit.Type.TEXT, text_markdown="# Offline disabled"
    )

    assert unit.is_downloadable is False


def test_publish_creates_immutable_canonical_snapshot_and_preserves_draft() -> None:
    vendor, course, user = make_course()
    asset = make_asset(vendor, user)
    _, lesson = make_published_tree(course, asset)

    revision = publish_course(course, created_by=user)
    course.refresh_from_db()
    lesson.title = "Edited draft"
    lesson.save(update_fields=("title",))

    assert revision.revision_number == 1
    assert course.offline_revision == 2
    assert course.current_revision == revision
    assert course.status == Course.Status.PUBLISHED
    assert len(revision.snapshot_sha256) == 64
    assert revision.snapshot_json["modules"][0]["lessons"][0]["title"] == "Lesson"
    assert list(CourseRevisionAsset.objects.values_list("media_asset_id", flat=True)) == [asset.id]
    with pytest.raises(ValidationError, match="immutable"):
        revision.snapshot_json = {"changed": True}
        revision.save()
    with pytest.raises(IntegrityError):
        asset.delete()


def test_republishing_increments_offline_revision_and_keeps_old_snapshot() -> None:
    _, course, _ = make_course()
    _, lesson = make_published_tree(course)
    first = publish_course(course)
    lesson.title = "Second draft"
    lesson.save(update_fields=("title",))

    second = publish_course(course)
    course.refresh_from_db()

    assert (first.revision_number, second.revision_number, course.offline_revision) == (1, 2, 3)
    assert first.snapshot_json["modules"][0]["lessons"][0]["title"] == "Lesson"
    assert second.snapshot_json["modules"][0]["lessons"][0]["title"] == "Second draft"


@pytest.mark.parametrize(
    ("asset_vendor", "kind", "status", "message"),
    [
        ("other", "video", "ready", "different vendor"),
        ("same", "audio", "pending", "not ready"),
        ("same", "audio", "ready", "incompatible"),
    ],
)
def test_publish_rejects_foreign_unready_and_incompatible_media(
    asset_vendor: str, kind: str, status: str, message: str
) -> None:
    vendor, course, user = make_course()
    asset = make_asset(
        Vendor.objects.create(name="Other", slug="other") if asset_vendor == "other" else vendor,
        user,
        kind=kind,
        status=status,
    )
    make_published_tree(course, asset)

    with pytest.raises(PublicationValidationError, match=message):
        publish_course(course)


def test_publish_rejects_empty_published_lesson() -> None:
    _, course, _ = make_course()
    module = create_module(course, title="Module", description="")
    create_lesson(module, title="Empty", description="", is_published=True)

    with pytest.raises(PublicationValidationError, match="at least one content unit"):
        publish_course(course)


def test_content_unit_checks_markdown_and_content_shape() -> None:
    _, course, _ = make_course()
    _, lesson = make_published_tree(course)
    unit = lesson.content_units.get()
    unit.text_markdown = "<script>alert(1)</script>"
    with pytest.raises(ValidationError, match="Raw HTML"):
        unit.full_clean()

    with pytest.raises(IntegrityError):
        ContentUnit.objects.create(
            lesson=lesson,
            type=ContentUnit.Type.TEXT,
            position=2,
            text_markdown=None,
        )


def test_position_services_keep_positions_dense() -> None:
    _, course, _ = make_course()
    module = create_module(course, title="One", description="")
    create_module(course, title="Two", description="")
    third = create_module(course, title="Three", description="")
    first_lesson = create_lesson(module, title="First", description="")
    second_lesson = create_lesson(module, title="Second", description="")
    first_unit = create_content_unit(first_lesson, type=ContentUnit.Type.TEXT, text_markdown="A")
    second_unit = create_content_unit(first_lesson, type=ContentUnit.Type.TEXT, text_markdown="B")

    move_module(third, 1)
    move_content_unit(second_unit, 1)

    assert list(Module.objects.filter(course=course).values_list("position", flat=True)) == [
        1,
        2,
        3,
    ]
    assert list(Lesson.objects.filter(module=module).values_list("position", flat=True)) == [1, 2]
    assert list(
        ContentUnit.objects.filter(lesson=first_lesson).values_list("position", flat=True)
    ) == [1, 2]
    assert first_unit.pk != second_unit.pk
    assert second_lesson.position == 2


def test_deleting_positioned_items_closes_gaps() -> None:
    _, course, _ = make_course()
    first = create_module(course, title="One", description="")
    second = create_module(course, title="Two", description="")
    third = create_module(course, title="Three", description="")
    lesson = create_lesson(first, title="Lesson", description="")
    first_unit = create_content_unit(lesson, type=ContentUnit.Type.TEXT, text_markdown="A")
    create_content_unit(lesson, type=ContentUnit.Type.TEXT, text_markdown="B")

    delete_module(second)
    delete_content_unit(first_unit)

    assert list(Module.objects.filter(course=course).values_list("position", flat=True)) == [1, 2]
    assert third.position == 3
    assert list(ContentUnit.objects.filter(lesson=lesson).values_list("position", flat=True)) == [1]
