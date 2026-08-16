# 0010 was amended in place to seed `features.manuscriptDescriptions`; a
# database that already applied it will never re-run it, so backfill that leaf.
import json

from django.db import migrations

KEY = "site_features.features.manuscriptDescriptions"


def seed_features_flag(apps, schema_editor):
    apps.get_model("common", "AppSettings").objects.get_or_create(
        key=KEY,
        defaults={
            "value": json.dumps(True),
            "description": "Site feature setting 'features.manuscriptDescriptions' (public site-features config).",
            "is_public": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0010_seed_site_features"),
    ]

    operations = [
        # Reverse is a no-op: 0010 owns the row on a database seeded after the amendment.
        migrations.RunPython(seed_features_flag, migrations.RunPython.noop),
    ]
