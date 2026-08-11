from django.db import migrations

LOG_LEVEL_DESCRIPTION = (
    "Runtime override for the `apps`/`django` logger levels. One of DEBUG, "
    "INFO, WARNING, ERROR, CRITICAL. Applied on process start by "
    "apps.common.apps.CommonConfig.ready(); falls back to the static "
    "APP_LOG_LEVEL env default (ERROR) when unset/inactive/invalid."
)


def seed_log_level(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")
    AppSettings.objects.get_or_create(
        key="LOG_LEVEL",
        defaults={"value": "ERROR", "description": LOG_LEVEL_DESCRIPTION},
    )


def unseed_log_level(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")
    AppSettings.objects.filter(key="LOG_LEVEL").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0009_appsettings"),
    ]

    operations = [
        migrations.RunPython(seed_log_level, unseed_log_level),
    ]
