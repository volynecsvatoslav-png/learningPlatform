import hashlib
import json
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, QuerySet
from django.utils import timezone

from learning.models import ContentUnit, Course, CourseRevision, CourseRevisionAsset, Lesson, Module


class MediaAssetLike(Protocol):
    id: Any
    vendor_id: Any
    kind: str
    status: str


MediaLookup = Callable[[Any], MediaAssetLike]
Positioned = TypeVar("Positioned", Module, Lesson, ContentUnit)


class PublicationValidationError(ValidationError):
    pass


def _default_media_lookup(asset_id: Any) -> MediaAssetLike:
    try:
        from media_assets.models import MediaAsset
    except ImportError as error:
        raise PublicationValidationError(
            "MediaAsset validation requires the future media_assets app "
            "or an explicit media lookup."
        ) from error
    return MediaAsset.objects.get(pk=asset_id)


def _reposition(items: QuerySet[Positioned], item: Positioned, position: int) -> Positioned:
    siblings = list(items.select_for_update().order_by("position", "pk"))
    item = next(row for row in siblings if row.pk == item.pk)
    siblings.remove(item)
    destination = min(max(position, 1), len(siblings) + 1)
    siblings.insert(destination - 1, item)

    # Move every row above the current range before writing the new order. This keeps
    # PostgreSQL's positive-integer check and the unique parent/position constraint valid.
    max_position = max((sibling.position for sibling in siblings), default=0)
    offset = max_position + len(siblings) + 1
    for index, sibling in enumerate(siblings, start=1):
        sibling.position = offset + index
        sibling.save(update_fields=("position",))
    for index, sibling in enumerate(siblings, start=1):
        sibling.position = index
        sibling.save(update_fields=("position",))
    return item


def _normalize_positions(items: QuerySet[Positioned]) -> None:  # noqa: UP047
    siblings = list(items.select_for_update().order_by("position", "pk"))
    offset = max((sibling.position for sibling in siblings), default=0) + len(siblings) + 1
    for index, sibling in enumerate(siblings, start=1):
        sibling.position = offset + index
        sibling.save(update_fields=("position",))
    for index, sibling in enumerate(siblings, start=1):
        sibling.position = index
        sibling.save(update_fields=("position",))


@transaction.atomic
def move_module(module: Module, position: int) -> Module:
    module_course_id = Module.objects.only("course_id").get(pk=module.pk).course_id
    Course.objects.select_for_update().get(pk=module_course_id)
    locked = Module.objects.select_for_update().get(pk=module.pk)
    return _reposition(Module.objects.filter(course_id=locked.course_id), locked, position)


@transaction.atomic
def move_lesson(lesson: Lesson, position: int) -> Lesson:
    lesson_module_id = Lesson.objects.only("module_id").get(pk=lesson.pk).module_id
    Module.objects.select_for_update().get(pk=lesson_module_id)
    locked = Lesson.objects.select_for_update().get(pk=lesson.pk)
    return _reposition(Lesson.objects.filter(module_id=locked.module_id), locked, position)


@transaction.atomic
def move_content_unit(content_unit: ContentUnit, position: int) -> ContentUnit:
    unit_lesson_id = ContentUnit.objects.only("lesson_id").get(pk=content_unit.pk).lesson_id
    Lesson.objects.select_for_update().get(pk=unit_lesson_id)
    locked = ContentUnit.objects.select_for_update().get(pk=content_unit.pk)
    return _reposition(ContentUnit.objects.filter(lesson_id=locked.lesson_id), locked, position)


@transaction.atomic
def create_module(course: Course, *, position: int | None = None, **values: Any) -> Module:
    locked_course = Course.objects.select_for_update().get(pk=course.pk)
    item = Module.objects.create(
        course=locked_course,
        position=Module.objects.filter(course=locked_course).count() + 1,
        **values,
    )
    return move_module(item, position or item.position)


@transaction.atomic
def create_lesson(module: Module, *, position: int | None = None, **values: Any) -> Lesson:
    locked_module = Module.objects.select_for_update().get(pk=module.pk)
    item = Lesson.objects.create(
        module=locked_module,
        position=Lesson.objects.filter(module=locked_module).count() + 1,
        **values,
    )
    return move_lesson(item, position or item.position)


@transaction.atomic
def create_content_unit(
    lesson: Lesson, *, position: int | None = None, **values: Any
) -> ContentUnit:
    locked_lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
    item = ContentUnit.objects.create(
        lesson=locked_lesson,
        position=ContentUnit.objects.filter(lesson=locked_lesson).count() + 1,
        **values,
    )
    return move_content_unit(item, position or item.position)


@transaction.atomic
def delete_module(module: Module) -> None:
    locked = Module.objects.select_for_update().get(pk=module.pk)
    course_id = locked.course_id
    locked.delete()
    _normalize_positions(Module.objects.filter(course_id=course_id))


@transaction.atomic
def delete_lesson(lesson: Lesson) -> None:
    locked = Lesson.objects.select_for_update().get(pk=lesson.pk)
    module_id = locked.module_id
    locked.delete()
    _normalize_positions(Lesson.objects.filter(module_id=module_id))


@transaction.atomic
def delete_content_unit(content_unit: ContentUnit) -> None:
    locked = ContentUnit.objects.select_for_update().get(pk=content_unit.pk)
    lesson_id = locked.lesson_id
    locked.delete()
    _normalize_positions(ContentUnit.objects.filter(lesson_id=lesson_id))


def _validate_asset(
    asset_id: Any, expected_kind: str, course: Course, media_lookup: MediaLookup
) -> MediaAssetLike:
    try:
        asset = media_lookup(asset_id)
    except Exception as error:
        raise PublicationValidationError(f"Media asset {asset_id} was not found.") from error
    if asset.vendor_id != course.vendor_id:
        raise PublicationValidationError("Media asset belongs to a different vendor.")
    if asset.status != "ready":
        raise PublicationValidationError("Media asset is not ready.")
    if asset.kind != expected_kind:
        raise PublicationValidationError(
            f"Media asset kind {asset.kind!r} is incompatible with {expected_kind!r} content."
        )
    return asset


def _unit_snapshot(unit: ContentUnit) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(unit.id),
        "type": unit.type,
        "title": unit.title or None,
        "position": unit.position,
        "is_downloadable": unit.is_downloadable,
    }
    if unit.type == ContentUnit.Type.TEXT:
        result["text_markdown"] = unit.text_markdown
    else:
        result["media_asset_id"] = str(unit.media_asset_id)
    return result


@transaction.atomic
def publish_course(
    course: Course, *, created_by: Any = None, media_lookup: MediaLookup | None = None
) -> CourseRevision:
    course = Course.objects.select_for_update().get(pk=course.pk)
    if course.status == Course.Status.ARCHIVED:
        raise PublicationValidationError("Archived courses cannot be published.")
    media_lookup = media_lookup or _default_media_lookup

    assets: set[Any] = set()
    if course.cover_asset_id:
        _validate_asset(course.cover_asset_id, "image", course, media_lookup)
        assets.add(course.cover_asset_id)

    modules_snapshot: list[dict[str, Any]] = []
    published_lessons = 0
    for module in Module.objects.filter(course=course).order_by("position", "pk"):
        lessons_snapshot: list[dict[str, Any]] = []
        for lesson in Lesson.objects.filter(module=module, is_published=True).order_by(
            "position", "pk"
        ):
            units = list(ContentUnit.objects.filter(lesson=lesson).order_by("position", "pk"))
            if not units:
                raise PublicationValidationError(
                    f"Published lesson {lesson.id} must contain at least one content unit."
                )
            units_snapshot: list[dict[str, Any]] = []
            for unit in units:
                try:
                    unit.full_clean()
                except ValidationError as error:
                    raise PublicationValidationError(error.message_dict) from error
                if unit.type != ContentUnit.Type.TEXT:
                    _validate_asset(unit.media_asset_id, unit.type, course, media_lookup)
                    assets.add(unit.media_asset_id)
                units_snapshot.append(_unit_snapshot(unit))
            lessons_snapshot.append(
                {
                    "id": str(lesson.id),
                    "title": lesson.title,
                    "description": lesson.description,
                    "position": lesson.position,
                    "content_units": units_snapshot,
                }
            )
            published_lessons += 1
        if lessons_snapshot:
            modules_snapshot.append(
                {
                    "id": str(module.id),
                    "title": module.title,
                    "description": module.description,
                    "position": module.position,
                    "lessons": lessons_snapshot,
                }
            )

    if not published_lessons:
        raise PublicationValidationError("A course needs at least one published lesson.")

    revision_number = (
        CourseRevision.objects.filter(course=course).aggregate(Max("revision_number"))[
            "revision_number__max"
        ]
        or 0
    ) + 1
    snapshot = {
        "course_id": str(course.id),
        "revision_number": revision_number,
        "title": course.title,
        "slug": course.slug,
        "short_description": course.short_description,
        "description_markdown": course.description_markdown,
        "cover_asset_id": str(course.cover_asset_id) if course.cover_asset_id else None,
        "modules": modules_snapshot,
    }
    encoded_snapshot = json.dumps(
        snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    revision = CourseRevision.objects.create(
        course=course,
        revision_number=revision_number,
        snapshot_json=snapshot,
        snapshot_sha256=hashlib.sha256(encoded_snapshot).hexdigest(),
        created_by=created_by,
    )
    CourseRevisionAsset.objects.bulk_create(
        [
            CourseRevisionAsset(course_revision=revision, media_asset_id=asset_id)
            for asset_id in assets
        ]
    )
    course.offline_revision += 1
    course.current_revision = revision
    course.status = Course.Status.PUBLISHED
    course.published_at = timezone.now()
    course.save(
        update_fields=(
            "offline_revision",
            "current_revision",
            "status",
            "published_at",
            "updated_at",
        )
    )
    return revision
