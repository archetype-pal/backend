# 0010 was amended in place to seed the four `titleBar`/`navBar` theme
# colours and `branding.logoUrl`; a database that already applied it will
# never re-run it, so backfill those five leaves — the same pattern
# `0015_seed_theme_colors.py` used for the original three theme colours.
import json

from django.db import migrations

KEYS = {
    "site_features.theme.titleBarBackgroundColor": "#075783",
    "site_features.theme.titleBarTextColor": "#faf8f5",
    "site_features.theme.navBarBackgroundColor": "#075783",
    "site_features.theme.navBarTextColor": "#faf8f5",
    "site_features.branding.logoUrl": "",
}


def seed_branding_and_header_colors(apps, schema_editor):
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
        ("common", "0015_seed_theme_colors"),
    ]

    operations = [
        # Reverse is a no-op: 0010 owns the row on a database seeded after the amendment.
        migrations.RunPython(seed_branding_and_header_colors, migrations.RunPython.noop),
    ]
