from django.db import migrations

# Mirrors DEFAULT_LABELS in 0009_seed_sitelabels_defaults.py — duplicated here
# (migrations can't import from the live app) as the fallback for any key
# that was somehow never present on the old singleton row.
DEFAULT_LABELS = {
    "historicalItem": {"en": "Historical Item", "fr": "Objet historique"},
    "catalogueNumber": {"en": "Catalogue Number", "fr": "Numéro de catalogue"},
    "position": {"en": "Position", "fr": "Position"},
    "date": {"en": "Date", "fr": "Date"},
    "appManuscripts": {"en": "Manuscripts", "fr": "Manuscrits"},
    "fieldHairType": {"en": "Hair Type", "fr": "Type de poil"},
    "fieldShelfmark": {"en": "Shelfmark", "fr": "Cote"},
    "fieldDateMinWeight": {"en": "Minimum weight", "fr": "Poids minimum"},
    "fieldDateMaxWeight": {"en": "Maximum weight", "fr": "Poids maximum"},
    "searchCategoryImages": {"en": "Images", "fr": "Images"},
    "searchCategoryScribes": {"en": "Scribes", "fr": "Copistes"},
    "searchCategoryHands": {"en": "Hands", "fr": "Mains"},
    "searchCategoryGraphs": {"en": "Graphs", "fr": "Graphes"},
    "searchCategoryTexts": {"en": "Texts", "fr": "Textes"},
    "searchCategoryClauses": {"en": "Clauses", "fr": "Clauses"},
    "searchCategoryPeople": {"en": "People", "fr": "Personnes"},
    "searchCategoryPlaces": {"en": "Places", "fr": "Lieux"},
    "siteTitle": {"en": "Models of Authority", "fr": "Models of Authority"},
    "siteTagline": {
        "en": "Archetype website tag line",
        "fr": "Archetype website tag line",
    },
    "footerLine1": {
        "en": "Footer first section",
        "fr": "Pied de page, première section ",
    },
    "footerLine2": {
        "en": "Footer second section",
        "fr": "Pied de page, deuxième section ",
    },
    "footerBottomLine": {
        "en": (
            "©2015–17 Models of Authority. Some parts available under CC-BY licence. "
            "All manuscript images are copyright of their respective repositories. "
            "Website by DDH / KDL. Built with Archetype."
        ),
        "fr": (
            "©2015–17 Models of Authority. Certaines parties sont disponibles sous licence CC-BY. "
            "Toutes les images de manuscrits sont la propriété de leurs dépôts respectifs. "
            "Site web par DDH / KDL. Construit avec Archetype."
        ),
    },
}


def migrate_labels(apps, schema_editor):
    OldSiteLabels = apps.get_model("common", "SiteLabels")
    NewSiteLabel = apps.get_model("common", "SiteLabel")

    old_row = OldSiteLabels.objects.filter(pk=1).first()
    old_labels = old_row.labels if old_row else {}

    for key, default_value in DEFAULT_LABELS.items():
        if isinstance(old_labels, dict) and key in old_labels:
            value = old_labels[key]
        else:
            value = default_value
        NewSiteLabel.objects.get_or_create(key=key, defaults={"value": value})


def unmigrate_labels(apps, schema_editor):
    NewSiteLabel = apps.get_model("common", "SiteLabel")
    NewSiteLabel.objects.filter(key__in=DEFAULT_LABELS.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0010_sitelabel"),
    ]

    operations = [
        migrations.RunPython(migrate_labels, unmigrate_labels),
    ]
