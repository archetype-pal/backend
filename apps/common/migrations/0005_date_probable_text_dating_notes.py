from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0004_editevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="date",
            name="dating_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="date",
            name="probable_text",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
