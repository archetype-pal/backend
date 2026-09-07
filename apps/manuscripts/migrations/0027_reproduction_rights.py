# Reproduction rights (AI programme W0.4). Every field defaults to empty or
# `unknown`, so the honest state before anyone asks an archive is 'not
# cleared' — nothing here grants a permission by omission.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manuscripts', '0026_alter_historicalitemdescription_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemimage',
            name='rights_statement',
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='repository',
            name='attribution',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='repository',
            name='derivative_release',
            field=models.CharField(choices=[('unknown', 'Unknown — not yet asked'), ('pending', 'Asked, awaiting an answer'), ('permitted', 'Permitted in writing'), ('prohibited', 'Refused')], default='unknown', max_length=16),
        ),
        migrations.AddField(
            model_name='repository',
            name='rights_notes',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='repository',
            name='rights_statement',
            field=models.URLField(blank=True, default=''),
        ),
    ]
