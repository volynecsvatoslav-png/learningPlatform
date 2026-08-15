from rest_framework import serializers

from learner.models import LessonProgress


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


class PwaSessionTransferConsumeSerializer(serializers.Serializer[dict[str, str]]):
    code = serializers.CharField(min_length=10, max_length=128, trim_whitespace=True)
