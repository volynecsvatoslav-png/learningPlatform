from rest_framework import serializers

from learner.models import Enrollment
from learning.models import ContentUnit, Course, Lesson, Module
from vendors.models import VendorMember


class VendorCourseSerializer(serializers.ModelSerializer[Course]):
    cover_asset_id = serializers.UUIDField(required=False, allow_null=True)
    published_revision = serializers.IntegerField(
        source="current_revision.revision_number", read_only=True
    )

    class Meta:
        model = Course
        fields = (
            "id",
            "vendor_id",
            "title",
            "slug",
            "short_description",
            "description_markdown",
            "cover_asset_id",
            "status",
            "offline_revision",
            "published_revision",
            "published_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "vendor_id",
            "status",
            "offline_revision",
            "published_revision",
            "published_at",
            "created_at",
            "updated_at",
        )


class VendorModuleSerializer(serializers.ModelSerializer[Module]):
    class Meta:
        model = Module
        fields = ("id", "course_id", "title", "description", "position")
        read_only_fields = ("id", "course_id")


class VendorLessonSerializer(serializers.ModelSerializer[Lesson]):
    class Meta:
        model = Lesson
        fields = ("id", "module_id", "title", "description", "position", "is_published")
        read_only_fields = ("id", "module_id")


class VendorContentUnitSerializer(serializers.ModelSerializer[ContentUnit]):
    class Meta:
        model = ContentUnit
        fields = (
            "id",
            "lesson_id",
            "type",
            "title",
            "position",
            "text_markdown",
            "media_asset_id",
            "is_downloadable",
        )
        read_only_fields = ("id", "lesson_id")


class StructureSerializer(serializers.Serializer[dict[str, object]]):
    entity = serializers.ChoiceField(choices=("module", "lesson", "content"))
    action = serializers.ChoiceField(choices=("create", "update", "delete", "move"))
    id = serializers.UUIDField(required=False)
    parent_id = serializers.UUIDField(required=False)
    position = serializers.IntegerField(required=False, min_value=1)
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_published = serializers.BooleanField(required=False)
    type = serializers.ChoiceField(choices=ContentUnit.Type.values, required=False)
    text_markdown = serializers.CharField(required=False, allow_blank=False)
    media_asset_id = serializers.UUIDField(required=False, allow_null=True)
    is_downloadable = serializers.BooleanField(required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        entity = attrs["entity"]
        action = attrs["action"]
        if action in {"update", "delete", "move"} and "id" not in attrs:
            raise serializers.ValidationError({"id": "This field is required."})
        if action == "move" and "position" not in attrs:
            raise serializers.ValidationError({"position": "This field is required."})
        if action == "create" and entity in {"lesson", "content"} and "parent_id" not in attrs:
            raise serializers.ValidationError({"parent_id": "This field is required."})
        if action == "create" and entity in {"module", "lesson"} and not attrs.get("title"):
            raise serializers.ValidationError({"title": "This field is required."})
        if entity == "content" and action == "create" and "type" not in attrs:
            raise serializers.ValidationError({"type": "This field is required."})
        if entity == "content" and action in {"create", "update"}:
            content_type = attrs.get("type")
            if content_type == ContentUnit.Type.TEXT:
                if not str(attrs.get("text_markdown", "")).strip():
                    raise serializers.ValidationError(
                        {"text_markdown": "Text content requires Markdown."}
                    )
                if attrs.get("media_asset_id") is not None:
                    raise serializers.ValidationError(
                        {"media_asset_id": "Text content cannot have media."}
                    )
            elif content_type in {
                ContentUnit.Type.IMAGE,
                ContentUnit.Type.AUDIO,
                ContentUnit.Type.VIDEO,
            } and not attrs.get("media_asset_id"):
                raise serializers.ValidationError(
                    {"media_asset_id": "Media content requires an asset."}
                )
        if action == "update" and not any(
            field in attrs
            for field in (
                "title",
                "description",
                "is_published",
                "type",
                "text_markdown",
                "media_asset_id",
                "is_downloadable",
            )
        ):
            raise serializers.ValidationError("Provide at least one field to update.")
        return attrs


class AccessGrantSerializer(serializers.Serializer[dict[str, object]]):
    vendor_id = serializers.UUIDField()
    learner_email = serializers.EmailField()
    course_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class EnrollmentSerializer(serializers.ModelSerializer[Enrollment]):
    course_title = serializers.CharField(source="course.title", read_only=True)
    learner_email = serializers.CharField(source="learner.email", read_only=True)

    class Meta:
        model = Enrollment
        fields = (
            "id",
            "learner_email",
            "course_id",
            "course_title",
            "status",
            "granted_at",
            "revoked_at",
        )
        read_only_fields = fields


class VendorMemberSerializer(serializers.ModelSerializer[VendorMember]):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = VendorMember
        fields = ("id", "vendor_id", "email", "role", "created_at")
        read_only_fields = ("id", "vendor_id", "email", "created_at")


class VendorMemberWriteSerializer(serializers.Serializer[dict[str, object]]):
    vendor_id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=(VendorMember.Role.EDITOR,))
    password = serializers.CharField(min_length=15, write_only=True)
