from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contentunit",
            name="is_downloadable",
            field=models.BooleanField(default=False),
        ),
    ]
