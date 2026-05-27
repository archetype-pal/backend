import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def copy_date_metadata_to_assessments(apps, schema_editor):
    Date = apps.get_model("common", "Date")
    HistoricalItem = apps.get_model("manuscripts", "HistoricalItem")
    HistoricalItemDateAssessment = apps.get_model("manuscripts", "HistoricalItemDateAssessment")

    dates = Date.objects.filter(Q(probable_text__gt="") | Q(dating_notes__gt=""))
    for date in dates.iterator():
        historical_item_ids = HistoricalItem.objects.filter(date_id=date.id).values_list("id", flat=True)
        for historical_item_id in historical_item_ids.iterator():
            HistoricalItemDateAssessment.objects.update_or_create(
                historical_item_id=historical_item_id,
                date_id=date.id,
                defaults={
                    "probable_text_date": date.probable_text,
                    "dating_notes": date.dating_notes,
                },
            )


def copy_assessments_to_date_metadata(apps, schema_editor):
    Date = apps.get_model("common", "Date")
    HistoricalItemDateAssessment = apps.get_model("manuscripts", "HistoricalItemDateAssessment")

    for assessment in HistoricalItemDateAssessment.objects.order_by("date_id", "id").iterator():
        Date.objects.filter(id=assessment.date_id).update(
            probable_text=assessment.probable_text_date,
            dating_notes=assessment.dating_notes,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0005_date_probable_text_dating_notes"),
        ("manuscripts", "0020_imagetext_content_dpt_legacy"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalItemDateAssessment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("probable_text_date", models.CharField(blank=True, default="", max_length=100)),
                ("dating_notes", models.TextField(blank=True, default="")),
                (
                    "date",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="historical_item_assessments",
                        to="common.date",
                    ),
                ),
                (
                    "historical_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="date_assessments",
                        to="manuscripts.historicalitem",
                        verbose_name="Historical Item",
                    ),
                ),
            ],
            options={
                "verbose_name": "Date Assessment",
                "ordering": ["historical_item", "date"],
            },
        ),
        migrations.AddConstraint(
            model_name="historicalitemdateassessment",
            constraint=models.UniqueConstraint(
                fields=("historical_item", "date"),
                name="historical_item_date_assessment_unique",
            ),
        ),
        migrations.RunPython(copy_date_metadata_to_assessments, copy_assessments_to_date_metadata),
    ]
