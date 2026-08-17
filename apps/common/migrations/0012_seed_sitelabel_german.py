# Backfills a German ("de") entry into every SiteLabel.value dict. 0008 only
# ever seeded en/fr, so this amends existing rows in place rather than
# recreating them (mirrors the amend-in-place approach 0011 used for
# AppSettings). Mirrors the German additions to DEFAULT_MODEL_LABELS in the
# frontend's lib/model-labels.ts — kept in sync manually, same as 0008.
from django.db import migrations

DEFAULT_LABELS_DE = {
    "historicalItem": "Historisches Objekt",
    "catalogueNumber": "Katalognummer",
    "position": "Position",
    "date": "Datum",
    "appManuscripts": "Manuskripte",
    "fieldHairType": "Haartyp",
    "fieldShelfmark": "Signatur",
    "fieldDateMinWeight": "Mindestgewicht",
    "fieldDateMaxWeight": "Höchstgewicht",
    "searchCategoryImages": "Bilder",
    "searchCategoryScribes": "Schreiber",
    "searchCategoryHands": "Hände",
    "searchCategoryGraphs": "Grapheme",
    "searchCategoryTexts": "Texte",
    "searchCategoryClauses": "Klauseln",
    "searchCategoryPeople": "Personen",
    "searchCategoryPlaces": "Orte",
    "siteTitle": "Models of Authority",
    "siteTagline": "Archetype website tag line",
    "footerLine1": "Fußzeile, erster Abschnitt",
    "footerLine2": "Fußzeile, zweiter Abschnitt",
    "footerBottomLine": "Fußzeile, unterer Abschnitt"
}


def seed_german_labels(apps, schema_editor):
    SiteLabel = apps.get_model("common", "SiteLabel")

    for key, de_text in DEFAULT_LABELS_DE.items():
        row, created = SiteLabel.objects.get_or_create(key=key, defaults={"value": {"de": de_text}})
        if not created and "de" not in row.value:
            row.value = {**row.value, "de": de_text}
            row.save(update_fields=["value"])


def unseed_german_labels(apps, schema_editor):
    SiteLabel = apps.get_model("common", "SiteLabel")

    for row in SiteLabel.objects.filter(key__in=DEFAULT_LABELS_DE):
        if "de" in row.value:
            value = dict(row.value)
            del value["de"]
            row.value = value
            row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0011_seed_features_flag"),
    ]

    operations = [
        migrations.RunPython(seed_german_labels, unseed_german_labels),
    ]
