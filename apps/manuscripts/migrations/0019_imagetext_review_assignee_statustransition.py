# Phase G — review queue.
# Adds the `review_assignee` FK to ImageText (who the editor nominated to
# review a draft) and the `StatusTransition` audit table.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0018_imagetext_unique_per_kind"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="imagetext",
            name="review_assignee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="image_texts_assigned_for_review",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="StatusTransition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "from_status",
                    models.CharField(
                        choices=[
                            ("Draft", "Draft"),
                            ("Review", "Review"),
                            ("Live", "Live"),
                            ("Reviewed", "Reviewed"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "to_status",
                    models.CharField(
                        choices=[
                            ("Draft", "Draft"),
                            ("Review", "Review"),
                            ("Live", "Live"),
                            ("Reviewed", "Reviewed"),
                        ],
                        max_length=16,
                    ),
                ),
                ("note", models.TextField(blank=True, default="")),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="status_transitions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "image_text",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="status_transitions",
                        to="manuscripts.imagetext",
                    ),
                ),
            ],
            options={
                "ordering": ["-created"],
                "indexes": [models.Index(fields=["image_text", "-created"], name="manuscripts_image_t_430251_idx")],
            },
        ),
    ]
