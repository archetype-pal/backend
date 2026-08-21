from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0016_copy_hand_description_to_handdescription'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='hand',
            name='description',
        ),
    ]
