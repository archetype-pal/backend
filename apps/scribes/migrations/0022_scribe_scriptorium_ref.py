import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0019_place_name_ci_unique'),
        ('scribes', '0021_script_name_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='scribe',
            name='scriptorium_ref',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='scribes',
                to='common.place',
            ),
        ),
    ]
