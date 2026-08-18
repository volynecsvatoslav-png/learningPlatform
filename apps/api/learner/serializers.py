from rest_framework import serializers

from learner.models import LessonProgress
from learner.services import DeviceProofError, normalize_public_jwk, require_p256_jwk


class LearnerProgressSerializer(serializers.ModelSerializer[LessonProgress]):
    percent = serializers.IntegerField(min_value=0, max_value=100)
    status = serializers.ChoiceField(choices=("in_progress", "completed"), required=False)

    class Meta:
        model = LessonProgress
        fields = ("lesson_id", "percent", "status", "completed_at", "updated_at")
        read_only_fields = ("lesson_id", "completed_at", "updated_at")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs.get("status") == "completed" and attrs.get("percent") != 100:
            raise serializers.ValidationError({"percent": "Completed progress must be 100%."})
        return attrs


class PublicKeyField(serializers.JSONField):
    def to_internal_value(self, data: object) -> dict[str, str]:
        value = super().to_internal_value(data)  # type: ignore[arg-type]
        if not isinstance(value, dict):
            raise serializers.ValidationError("Public key must be a JSON object.")
        try:
            return require_p256_jwk(normalize_public_jwk(value))
        except DeviceProofError as error:
            raise serializers.ValidationError(str(error)) from error


class AccessInspectSerializer(serializers.Serializer[dict[str, object]]):
    token = serializers.CharField(min_length=20, max_length=256, trim_whitespace=True)
    installation_id = serializers.UUIDField()
    public_key_jwk = PublicKeyField()


class AccessExchangeSerializer(AccessInspectSerializer):
    challenge = serializers.CharField(min_length=20, max_length=64, trim_whitespace=True)
    signature = serializers.CharField(min_length=20, max_length=512, trim_whitespace=True)
    confirm_transfer = serializers.BooleanField(required=False, default=False)


class RecoveryExchangeSerializer(serializers.Serializer[dict[str, object]]):
    recovery_token = serializers.CharField(min_length=20, max_length=256, trim_whitespace=True)
    installation_id = serializers.UUIDField()
    public_key_jwk = PublicKeyField()
    signature = serializers.CharField(min_length=20, max_length=512, trim_whitespace=True)
