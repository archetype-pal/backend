from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0027_embed_text_region_links"),
    ]

    operations = [
        migrations.AlterField(
            model_name="imagetext",
            name="content",
            field=models.TextField(blank=True, default=""),
        ),
    ]
