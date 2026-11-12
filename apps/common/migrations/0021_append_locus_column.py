import json

from django.db import migrations

KEY = "site_features.searchCategories.manuscripts.visibleColumns"
NEW_COLUMNS = ["Locus"]
ANCHOR = "Shelfmark"


def _stored_columns(row) -> list | None:
    try:
        columns = json.loads(row.value)
    except (TypeError, ValueError):
        return None
    return columns if isinstance(columns, list) else None


def append_locus_column(apps, schema_editor):
    row = apps.get_model("common", "AppSettings").objects.filter(key=KEY).first()
    columns = _stored_columns(row) if row else None
    if columns is None:
        return

    missing = [column for column in NEW_COLUMNS if column not in columns]
    if not missing:
        return

    at = columns.index(ANCHOR) + 1 if ANCHOR in columns else len(columns)
    row.value = json.dumps(columns[:at] + missing + columns[at:])
    row.save(update_fields=["value"])


def remove_locus_column(apps, schema_editor):
    row = apps.get_model("common", "AppSettings").objects.filter(key=KEY).first()
    columns = _stored_columns(row) if row else None
    if columns is None:
        return

    row.value = json.dumps([column for column in columns if column not in NEW_COLUMNS])
    row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0020_alter_editevent_action"),
    ]

    operations = [
        migrations.RunPython(append_locus_column, remove_locus_column),
    ]
