from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("publications", "0005_comment_parent"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="disqus_id",
            field=models.CharField(blank=True, editable=False, max_length=32, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="comment",
            name="author_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
