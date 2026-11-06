from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('manuscripts', '0033_copy_repository_place_to_place_ref'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='repository',
            name='place',
        ),
        migrations.RenameField(
            model_name='repository',
            old_name='place_ref',
            new_name='place',
        ),
    ]
