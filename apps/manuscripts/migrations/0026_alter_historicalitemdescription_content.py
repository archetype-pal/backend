# Mirrors MsDescArea.content: since a catalogue description can be converted to
# TEI prose and cleared mid-edit (docs/tei.md 4.5), a bare TextField() would
# render as required/allow_blank=False in DRF and 400 on an emptied PATCH.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0025_drop_content_dpt_legacy"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalitemdescription",
            name="content",
            field=models.TextField(blank=True, default=""),
        ),
    ]
