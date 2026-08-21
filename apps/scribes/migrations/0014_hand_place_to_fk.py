from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0013_copy_hand_place_to_place_ref'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='hand',
            name='place',
        ),
        migrations.RenameField(
            model_name='hand',
            old_name='place_ref',
            new_name='place',
        ),
    ]
