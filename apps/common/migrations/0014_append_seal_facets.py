# Append the seal facets to the stored `visibleFacets` list.
#
# `site_features.searchCategories.<type>.visibleFacets` is an EXPLICIT list, not
# an allow-by-default flag like `features.*` (which is read `!== false`, so an
# unknown key stays on). A facet the stored list has never heard of is therefore
# invisible — the registry can declare it, the index can carry it and the API can
# return it, and the rail still will not show it.
#
# So a new facet needs a migration that appends it, exactly as
# `0011_seed_features_flag` backfilled a new feature leaf. Appending — rather
# than rewriting the list — preserves an admin's deliberate choice to hide any of
# the facets they already know about.

import json

from django.db import migrations

KEY = "site_features.searchCategories.manuscripts.visibleFacets"
NEW_FACETS = ["seal_type", "seal_material"]
# Keep the rail's grouping: the seal facets belong with the other msDesc-derived
# ones rather than at the end, after the catalogue facets.
ANCHOR = "deco_type"


def append_seal_facets(apps, schema_editor):
    settings_model = apps.get_model("common", "AppSettings")
    row = settings_model.objects.filter(key=KEY).first()
    if row is None:
        return  # A database seeded after this ships gets the full list from 0010.

    try:
        facets = json.loads(row.value)
    except (TypeError, ValueError):  # fmt: skip
        return
    if not isinstance(facets, list):
        return

    missing = [facet for facet in NEW_FACETS if facet not in facets]
    if not missing:
        return

    at = facets.index(ANCHOR) + 1 if ANCHOR in facets else len(facets)
    row.value = json.dumps(facets[:at] + missing + facets[at:])
    row.save(update_fields=["value"])


def remove_seal_facets(apps, schema_editor):
    settings_model = apps.get_model("common", "AppSettings")
    row = settings_model.objects.filter(key=KEY).first()
    if row is None:
        return
    try:
        facets = json.loads(row.value)
    except (TypeError, ValueError):  # fmt: skip
        return
    if not isinstance(facets, list):
        return
    row.value = json.dumps([facet for facet in facets if facet not in NEW_FACETS])
    row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0013_merge_20260826_1201"),
    ]

    operations = [
        migrations.RunPython(append_seal_facets, remove_seal_facets),
    ]
