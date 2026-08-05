# Data migration (no schema change): seeds a couple of illustrative
# feature-flag rows into AppSettings.
#
# There is no pre-existing `site-features.json` (or any feature-flag JSON) in
# this repo to migrate, and a codebase-wide search turned up no ad-hoc
# boolean-env-var-gated behaviour that would clearly benefit from becoming a
# runtime-toggleable flag instead (the one superficially similar candidate,
# `SEARCH_AUTO_REINDEX` in config/settings.py, is unused dead config — nothing
# reads it — and the actual item-parts reindex-on-save in
# apps/search/signals.py is explicitly documented as an unconditional
# INVARIANT, so gating it behind a flag would fight the existing design
# rather than migrate an existing one).
#
# These two rows are therefore purely illustrative: they demonstrate the
# `AppSettings`-backed flag pattern (read via
# `apps.common.services.is_feature_enabled`) without pretending to gate a
# real product feature. Safe to delete once a genuine flag need arises.
from django.db import migrations

EXAMPLE_FLAGS = {
    "example_feature_flag_enabled": {
        "value": "true",
        "description": (
            "Illustrative example seeded to demonstrate the AppSettings-backed "
            "feature-flag pattern (see apps.common.services.is_feature_enabled). "
            "Not wired to any behaviour; safe to remove."
        ),
    },
    "example_feature_flag_disabled": {
        "value": "false",
        "description": (
            "Illustrative example seeded to demonstrate the AppSettings-backed "
            "feature-flag pattern (see apps.common.services.is_feature_enabled). "
            "Not wired to any behaviour; safe to remove."
        ),
    },
}


def seed_example_flags(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")

    for key, fields in EXAMPLE_FLAGS.items():
        AppSettings.objects.get_or_create(key=key, defaults=fields)


def unseed_example_flags(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")
    AppSettings.objects.filter(key__in=EXAMPLE_FLAGS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0009_appsettings"),
    ]

    operations = [
        migrations.RunPython(seed_example_flags, unseed_example_flags),
    ]
