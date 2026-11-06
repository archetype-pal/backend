import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("publications", "0004_allow_blank_publication_draft_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="replies",
                to="publications.comment",
            ),
        ),
    ]
