from rest_framework import serializers

from learner.models import LessonProgress


class LearnerProgressSerializer(serializers.ModelSerializer[LessonProgress]):
    class Meta:
        model = LessonProgress
        fields = ("lesson_id", "percent", "status", "completed_at", "updated_at")
        read_only_fields = ("lesson_id", "completed_at", "updated_at")

    def validate_percent(self, value: int) -> int:
        if not 0 <= value <= 100:
            raise serializers.ValidationError("Процент должен быть от 0 до 100.")
        return value
