import re
from pathlib import Path
from typing import cast

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from rest_framework import serializers

from media_assets.models import MediaAsset
from media_assets.validation import ALLOWED_EXTENSIONS

ALLOWED_CONTENT_TYPES: dict[str, set[str]] = {
    MediaAsset.Kind.IMAGE: {"image/jpeg", "image/png", "image/webp"},
    MediaAsset.Kind.AUDIO: {"audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "application/ogg"},
    MediaAsset.Kind.VIDEO: {"video/mp4"},
}


class UploadRequestSerializer(serializers.Serializer[dict[str, object]]):
    vendor_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=MediaAsset.Kind.values)
    original_name = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)
    sha256 = serializers.CharField(min_length=64, max_length=64)

    def validate_sha256(self, value: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise serializers.ValidationError("Must be a SHA-256 hexadecimal digest.")
        return value.lower()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        kind = attrs["kind"]
        original_name = attrs["original_name"]
        size_bytes = attrs["size_bytes"]
        content_type = attrs["content_type"]
        if not isinstance(kind, str):
            raise serializers.ValidationError("Invalid upload request.")
        if not isinstance(original_name, str):
            raise serializers.ValidationError("Invalid upload request.")
        if not isinstance(size_bytes, int):
            raise serializers.ValidationError("Invalid upload request.")
        if not isinstance(content_type, str):
            raise serializers.ValidationError("Invalid upload request.")
        if Path(original_name).suffix.lower() not in ALLOWED_EXTENSIONS[kind]:
            raise serializers.ValidationError({"original_name": "File extension is not allowed."})
        limit = settings.MEDIA_MAX_BYTES[kind]
        if size_bytes > limit:
            raise serializers.ValidationError(
                {"size_bytes": "Declared size exceeds the allowed limit."}
            )
        if content_type.lower() not in ALLOWED_CONTENT_TYPES[kind]:
            raise serializers.ValidationError(
                {"content_type": "Content type is not allowed for this media type."}
            )
        return attrs


class ProxyUploadSerializer(serializers.Serializer[dict[str, object]]):
    vendor_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=MediaAsset.Kind.values)
    file = serializers.FileField(allow_empty_file=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        file = cast(UploadedFile, attrs["file"])
        kind = cast(str, attrs["kind"])
        name = str(file.name)
        if name != Path(name).name or "/" in name or "\\" in name:
            raise serializers.ValidationError({"file": "Path separators are not allowed."})
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS[kind]:
            raise serializers.ValidationError({"file": "Unsupported file format."})
        if str(file.content_type or "").lower() not in ALLOWED_CONTENT_TYPES[kind]:
            raise serializers.ValidationError({"file": "Invalid MIME type."})
        size = int(file.size or 0)
        if size <= 0:
            raise serializers.ValidationError({"file": "File must not be empty."})
        if size > settings.MEDIA_MAX_BYTES[kind]:
            raise serializers.ValidationError({"file": "File exceeds the maximum size."})
        return attrs


class MediaAssetSerializer(serializers.ModelSerializer[MediaAsset]):
    class Meta:
        model = MediaAsset
        fields = (
            "id",
            "vendor_id",
            "kind",
            "status",
            "original_name",
            "content_type",
            "size_bytes",
            "sha256",
            "duration_seconds",
            "width",
            "height",
            "rejection_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
