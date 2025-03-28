# Generated by Django 5.1.6 on 2025-02-16 17:34

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manuscripts', '0002_itempart_current_item_locus_itempart_custom_label'),
    ]

    operations = [
        migrations.CreateModel(
            name='BibliographicSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('label', models.CharField(help_text='A shorthand for the reference (e.g. BL)', max_length=100)),
            ],
        ),
        migrations.AlterField(
            model_name='historicalitem',
            name='date',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name='historicalitem',
            name='format',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='manuscripts.itemformat'),
        ),
        migrations.AlterField(
            model_name='repository',
            name='place',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name='cataloguenumber',
            name='catalogue',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='manuscripts.bibliographicsource'),
        ),
        migrations.AlterField(
            model_name='historicalitemdescription',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='manuscripts.bibliographicsource'),
        ),
    ]
