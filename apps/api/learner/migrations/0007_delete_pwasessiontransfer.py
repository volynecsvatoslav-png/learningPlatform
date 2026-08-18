from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("learner", "0006_alter_enrollment_vendor"),
    ]

    operations = [
        migrations.DeleteModel(name="PwaSessionTransfer"),
    ]
