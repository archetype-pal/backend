# Generated by Django 5.1.5 on 2025-01-31 20:14

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('symbols_structure', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='allograph',
            name='aspects',
        ),
        migrations.DeleteModel(
            name='Aspect',
        ),
    ]
