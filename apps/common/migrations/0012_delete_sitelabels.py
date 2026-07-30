from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0011_migrate_sitelabels_data"),
    ]

    operations = [
        migrations.DeleteModel(
            name="SiteLabels",
        ),
    ]
