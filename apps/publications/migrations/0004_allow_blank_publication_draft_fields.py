import tinymce.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("publications", "0003_partner"),
    ]

    operations = [
        migrations.AlterField(
            model_name="publication",
            name="content",
            field=tinymce.models.HTMLField(blank=True),
        ),
        migrations.AlterField(
            model_name="publication",
            name="preview",
            field=tinymce.models.HTMLField(blank=True),
        ),
    ]
