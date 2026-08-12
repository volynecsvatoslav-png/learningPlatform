import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("vendors", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MediaAsset",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("image", "Изображение"), ("video", "Видео"), ("audio", "Аудио")], max_length=8)),
                ("status", models.CharField(choices=[("pending", "Ожидает загрузки"), ("uploaded", "Загружен"), ("validating", "Проверяется"), ("ready", "Готов"), ("rejected", "Отклонён")], default="pending", max_length=16)),
                ("bucket", models.CharField(max_length=255)),
                ("object_key", models.CharField(max_length=512, unique=True)),
                ("original_name", models.CharField(max_length=255)),
                ("content_type", models.CharField(max_length=127)),
                ("size_bytes", models.BigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("duration_seconds", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True)),
                ("width", models.PositiveIntegerField(blank=True, null=True)),
                ("height", models.PositiveIntegerField(blank=True, null=True)),
                ("rejection_reason", models.CharField(blank=True, max_length=200, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_media_assets", to=settings.AUTH_USER_MODEL)),
                ("vendor", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="media_assets", to="vendors.vendor")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(
            model_name="mediaasset",
            constraint=models.CheckConstraint(condition=models.Q(("size_bytes__gt", 0)), name="media_asset_size_bytes_positive"),
        ),
        migrations.AddIndex(
            model_name="mediaasset",
            index=models.Index(fields=["vendor", "status"], name="media_asset_vendor_status_idx"),
        ),
    ]
