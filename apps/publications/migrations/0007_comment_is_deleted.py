from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("publications", "0006_comment_disqus_id_optional_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
    ]
