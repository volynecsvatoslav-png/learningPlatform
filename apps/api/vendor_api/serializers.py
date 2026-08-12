from rest_framework import serializers

from learner.models import Enrollment
from learning.models import ContentUnit, Course, Lesson, Module
from media_assets.models import MediaAsset
from vendors.models import VendorMember


class VendorCourseSerializer(serializers.ModelSerializer[Course]):
    cover_asset_id = serializers.PrimaryKeyRelatedField(
        source="cover_asset", queryset=MediaAsset.objects.all(), required=False, allow_null=True
    )
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
    role = serializers.ChoiceField(choices=(VendorMember.Role.OWNER, VendorMember.Role.EDITOR))
    password = serializers.CharField(min_length=15, write_only=True)
