# 0010 was amended in place to seed `theme.*`; a database that already
# applied it will never re-run it, so backfill those three leaves.
import json

from django.db import migrations

KEYS = {
    "site_features.theme.primaryColor": "#075783",
    "site_features.theme.primaryForegroundColor": "#faf8f5",
    "site_features.theme.accentColor": "#f59f0a",
}


def seed_theme_colors(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")
    for key, value in KEYS.items():
        AppSettings.objects.get_or_create(
            key=key,
            defaults={
                "value": json.dumps(value),
                "description": f"Site feature setting '{key.removeprefix('site_features.')}' "
                "(public site-features config).",
                "is_public": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0011_seed_features_flag"),
    ]

    operations = [
        # Reverse is a no-op: 0010 owns the row on a database seeded after the amendment.
        migrations.RunPython(seed_theme_colors, migrations.RunPython.noop),
    ]
