# ROADMAP Phase H.11 — the drop 0024 deliberately withheld.
#
# Applied after `verify_tei_cutover --accept-superseded` passed against the
# corpus: 894 of 899 retained values regenerate from the TEI, and the 5 that do
# not (ImageText #535, #536, #573, #574, #579 — edited after the May migration)
# were reviewed and their pre-edit HTML accepted as expendable.
#
# The column is absent from model state since 0024, so this emits DDL only. It
# is guarded by introspection rather than `DROP COLUMN IF EXISTS` because SQLite
# — which the test suite uses — has no `IF EXISTS` on `ALTER TABLE`, and there
# the column never existed at all.

from django.db import migrations

TABLE = "manuscripts_imagetext"
COLUMN = "content_dpt_legacy"


def drop_column(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, TABLE)}
    if COLUMN in columns:
        schema_editor.execute(f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN}")


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0024_remove_imagetext_content_dpt_legacy"),
    ]

    operations = [
        migrations.RunPython(drop_column, migrations.RunPython.noop, elidable=False),
    ]
