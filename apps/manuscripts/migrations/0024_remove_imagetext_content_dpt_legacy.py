# ROADMAP Phase H.11 — the TEI cutover, STATE ONLY. This migration deliberately
# does NOT drop `manuscripts_imagetext.content_dpt_legacy` from the database.
#
# It originally issued the DROP. That made a routine deploy destructive: the
# documented upgrade step is `just migrate`, so any deployment would have
# dropped the retention column with no chance to run the gate first — and
# `verify_tei_cutover` against the live corpus shows 5 rows whose retained HTML
# is NOT reproducible from their TEI (editors changed those rows after the May
# migration), so the loss would have been silent and irreversible.
#
# The file is kept — rather than deleted — because developers have already
# pulled it. Deleting it would strand the node for anyone who applied it, and
# restoring the model field would then break every ImageText query against a
# database whose column is already gone. `SeparateDatabaseAndState` instead
# keeps the *state* change (so the field stays absent from the model and
# `makemigrations --check` is clean) while emitting no DDL, which leaves every
# database — applied or not — working:
#
#   * already applied the destructive version → column gone, model does not
#     reference it, migration recorded: nothing re-runs, nothing breaks;
#   * not yet applied → this no-ops, the column and its data survive.
#
# TO ACTUALLY DROP IT LATER: the model state already has the field removed, so
# `makemigrations` will not generate anything. Add a new migration containing
# only the DDL, e.g.
#     migrations.RunSQL(
#         "ALTER TABLE manuscripts_imagetext DROP COLUMN IF EXISTS content_dpt_legacy",
#         reverse_sql=migrations.RunSQL.noop,
#     )
# and run `python manage.py verify_tei_cutover --migrated-at <date>` against the
# target database first — it exits non-zero unless the drop provably loses
# nothing, and lists any row whose pre-edit HTML would be destroyed.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0023_msdescarea"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Model state only: `content_dpt_legacy` is gone from models.py, so
            # the migration graph must agree or every `makemigrations` run would
            # try to generate the removal again.
            state_operations=[
                migrations.RemoveField(
                    model_name="imagetext",
                    name="content_dpt_legacy",
                ),
            ],
            # Intentionally empty: no DROP COLUMN. See the header.
            database_operations=[],
        ),
    ]
