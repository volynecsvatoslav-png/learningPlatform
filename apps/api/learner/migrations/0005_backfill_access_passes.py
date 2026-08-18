import hashlib
import hmac
import secrets
import uuid

from django.conf import settings
from django.db import migrations


def backfill_vendor(apps, schema_editor):  # type: ignore[no-untyped-def]
    enrollment = apps.get_model("learner", "Enrollment")
    course = apps.get_model("learning", "Course")
    connection = schema_editor.connection
    enrollments = enrollment.objects.using(connection.alias).filter(vendor__isnull=True)
    for row in enrollments.select_related("course").iterator():
        enrollment.objects.using(connection.alias).filter(pk=row.pk).update(
            vendor_id=row.course.vendor_id
        )


def create_access_passes(apps, schema_editor):  # type: ignore[no-untyped-def]
    access_pass = apps.get_model("learner", "AccessPass")
    enrollment = apps.get_model("learner", "Enrollment")
    connection = schema_editor.connection
    pairs = (
        enrollment.objects.using(connection.alias)
        .filter(status="active")
        .values("vendor_id", "user_id")
        .distinct()
    )
    for pair in pairs.iterator():
        raw_token = secrets.token_urlsafe(32)
        token_hash = hmac.new(
            settings.ACCESS_TOKEN_PEPPER.encode(), raw_token.encode(), hashlib.sha256
        ).hexdigest()
        access_pass.objects.using(connection.alias).create(
            vendor_id=pair["vendor_id"],
            user_id=pair["user_id"],
            token_hash=token_hash,
            token_prefix=raw_token[:12],
            generation=1,
            status="active",
        )


def link_sessions(apps, schema_editor):  # type: ignore[no-untyped-def]
    access_pass = apps.get_model("learner", "AccessPass")
    learner_session = apps.get_model("learner", "LearnerSession")
    connection = schema_editor.connection
    orphan_sessions = (
        learner_session.objects.using(connection.alias)
        .filter(access_pass__isnull=True, revoked_at__isnull=True)
        .select_related("learner")
    )
    for session in orphan_sessions.iterator():
        passes = list(
            access_pass.objects.using(connection.alias)
            .filter(user_id=session.learner_id, status="active")
            .values_list("id", "generation")
        )
        if len(passes) != 1:
            continue
        pass_id, generation = passes[0]
        session_token_hash = hmac.new(
            settings.SESSION_TOKEN_PEPPER.encode(),
            session.session_key.encode(),
            hashlib.sha256,
        ).hexdigest()
        learner_session.objects.using(connection.alias).filter(pk=session.pk).update(
            access_pass_id=pass_id,
            pass_generation=generation,
            session_token_hash=session_token_hash,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("learner", "0004_accesspass_device_devicechallenge_offlinelicense_and_more")
    ]

    operations = [
        migrations.RunPython(backfill_vendor, migrations.RunPython.noop),
        migrations.RunPython(create_access_passes, migrations.RunPython.noop),
        migrations.RunPython(link_sessions, migrations.RunPython.noop),
    ]