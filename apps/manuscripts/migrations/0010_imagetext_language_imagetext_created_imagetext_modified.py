import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("manuscripts", "0009_alter_cataloguenumber_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="imagetext",
            name="language",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="imagetext",
            name="created",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="imagetext",
            name="modified",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
