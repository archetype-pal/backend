from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0003_alter_date_options"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("updated", "Updated"),
                            ("deleted", "Deleted"),
                            ("status_changed", "Status changed"),
                            ("commented", "Commented"),
                        ],
                        max_length=24,
                    ),
                ),
                ("target_type", models.CharField(db_index=True, max_length=64)),
                ("target_id", models.BigIntegerField(db_index=True)),
                ("summary", models.CharField(blank=True, default="", max_length=255)),
                ("payload", models.JSONField(blank=True, null=True)),
                ("created", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "actor",
                    models.ForeignKey(
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="edit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created"],
                "indexes": [
                    models.Index(fields=["target_type", "target_id"], name="editevent_target_idx"),
                ],
            },
        ),
    ]
