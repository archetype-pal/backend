import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0019_place_name_ci_unique'),
        ('manuscripts', '0031_alter_imagetext_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='repository',
            name='place_ref',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='repositories',
                to='common.place',
            ),
        ),
    ]
