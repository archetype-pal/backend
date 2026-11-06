from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("scribes", "0020_merge_duplicate_scripts")]

    operations = [
        migrations.AlterField(
            model_name="script",
            name="name",
            field=models.CharField(max_length=100, unique=True),
        ),
    ]
