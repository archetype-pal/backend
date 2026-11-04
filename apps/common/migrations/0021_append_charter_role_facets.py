# Append the charter-role facets to the stored texts `visibleFacets` list.
#
# The texts index now carries the granters, beneficiaries and witnesses a
# scholar approved for each charter (AI programme W2.1). The stored list is
# explicit, so a facet it predates stays hidden; see `0014_append_seal_facets`,
# which this follows. Appending rather than rewriting keeps an admin's choice to
# hide any facet already listed.

import json

from django.db import migrations

KEY = "site_features.searchCategories.texts.visibleFacets"
NEW_FACETS = ["granters", "beneficiaries", "witnesses"]
# Beside the facet for everyone a charter names, which these refine.
ANCHOR = "people"


def _stored_facets(row) -> list | None:
    try:
        facets = json.loads(row.value)
    except (TypeError, ValueError):  # fmt: skip
        return None
    return facets if isinstance(facets, list) else None


def append_charter_role_facets(apps, schema_editor):
    settings_model = apps.get_model("common", "AppSettings")
    row = settings_model.objects.filter(key=KEY).first()
    if row is None:
        return  # A database seeded after this ships gets the full list from 0010.
    facets = _stored_facets(row)
    if facets is None:
        return

    missing = [facet for facet in NEW_FACETS if facet not in facets]
    if not missing:
        return

    at = facets.index(ANCHOR) + 1 if ANCHOR in facets else len(facets)
    row.value = json.dumps(facets[:at] + missing + facets[at:])
    row.save(update_fields=["value"])


def remove_charter_role_facets(apps, schema_editor):
    settings_model = apps.get_model("common", "AppSettings")
    row = settings_model.objects.filter(key=KEY).first()
    if row is None:
        return
    facets = _stored_facets(row)
    if facets is None:
        return
    row.value = json.dumps([facet for facet in facets if facet not in NEW_FACETS])
    row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0020_alter_editevent_action"),
    ]

    operations = [
        migrations.RunPython(append_charter_role_facets, remove_charter_role_facets),
    ]
