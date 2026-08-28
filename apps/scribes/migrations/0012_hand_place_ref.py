import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0012_place'),
        ('scribes', '0011_hand_description_optional'),
    ]

    operations = [
        migrations.AddField(
            model_name='hand',
            name='place_ref',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='hands',
                to='common.place',
            ),
        ),
    ]
