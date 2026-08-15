import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def revoke_duplicate_active_sessions(apps, schema_editor):  # type: ignore[no-untyped-def]
    learner_session = apps.get_model("learner", "LearnerSession")
    seen: set[uuid.UUID] = set()
    now = timezone.now()
    active_sessions = learner_session.objects.using(schema_editor.connection.alias).filter(
        revoked_at__isnull=True
    ).order_by("learner_id", "-created_at", "-id")
    for session in active_sessions.iterator():
        if session.learner_id in seen:
            learner_session.objects.using(schema_editor.connection.alias).filter(
                pk=session.pk
            ).update(revoked_at=now)
        else:
            seen.add(session.learner_id)


class Migration(migrations.Migration):
    dependencies = [("learner", "0002_session_progress")]

    operations = [
        migrations.CreateModel(
            name="PwaSessionTransfer",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("code_hash", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "learner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pwa_session_transfers",
                        to="accounts.user",
                    ),
                ),
                (
                    "source_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pwa_transfers",
                        to="learner.learnersession",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["learner", "used_at", "expires_at"],
                        name="pwa_transfer_active_idx",
                    )
                ],
            },
        ),
        migrations.RunPython(revoke_duplicate_active_sessions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="learnersession",
            constraint=models.UniqueConstraint(
                condition=models.Q(("revoked_at__isnull", True)),
                fields=("learner",),
                name="learner_one_active_session",
            ),
        ),
    ]
