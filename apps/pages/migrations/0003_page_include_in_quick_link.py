from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pages', '0002_seed_legacy_about_pages'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='include_in_quick_link',
            field=models.BooleanField(
                default=False, help_text='Show this page as a quick link in the site footer.'
            ),
        ),
    ]
