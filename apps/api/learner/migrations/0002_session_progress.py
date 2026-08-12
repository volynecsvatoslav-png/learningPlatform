import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("learner", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="LearnerSession",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("session_key", models.CharField(max_length=40, unique=True)),
                ("device_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "learner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="learner_sessions",
                        to="accounts.user",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="LessonProgress",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("lesson_id", models.UUIDField()),
                ("percent", models.PositiveSmallIntegerField(default=0)),
                ("status", models.CharField(default="in_progress", max_length=16)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "course",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lesson_progress",
                        to="learning.course",
                    ),
                ),
                (
                    "learner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lesson_progress",
                        to="accounts.user",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="lessonprogress",
            constraint=models.UniqueConstraint(
                fields=("learner", "lesson_id"),
                name="learner_progress_learner_lesson_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="lessonprogress",
            constraint=models.CheckConstraint(
                condition=models.Q(("percent__gte", 0), ("percent__lte", 100)),
                name="learner_progress_percent_range",
            ),
        ),
    ]
