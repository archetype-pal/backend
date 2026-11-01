from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0020_copy_scribe_scriptorium_to_scriptorium_ref'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='scribe',
            name='scriptorium',
        ),
        migrations.RenameField(
            model_name='scribe',
            old_name='scriptorium_ref',
            new_name='scriptorium',
        ),
    ]
