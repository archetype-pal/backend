# Generated by Django 5.1.7 on 2025-05-02 06:05

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('manuscripts', '0007_alter_itemimage_image'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='historicalitem',
            name='issuer',
        ),
        migrations.RemoveField(
            model_name='historicalitem',
            name='named_beneficiary',
        ),
        migrations.RemoveField(
            model_name='historicalitem',
            name='neumed',
        ),
        migrations.RemoveField(
            model_name='historicalitem',
            name='vernacular',
        ),
    ]
