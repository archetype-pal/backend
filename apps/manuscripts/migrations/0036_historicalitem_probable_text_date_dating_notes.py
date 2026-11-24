from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manuscripts', '0035_historicalitemorigin'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalitem',
            name='probable_text_date',
            field=models.CharField(blank=True, db_default='', default='', max_length=100),
        ),
        migrations.AddField(
            model_name='historicalitem',
            name='dating_notes',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
    ]
