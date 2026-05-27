from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0021_historicalitemdateassessment"),
        ("common", "0005_date_probable_text_dating_notes"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="date",
            name="dating_notes",
        ),
        migrations.RemoveField(
            model_name="date",
            name="probable_text",
        ),
    ]
