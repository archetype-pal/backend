from django.db import migrations

# Mirrors DEFAULT_MODEL_LABELS in archetype3-frontend/lib/model-labels.ts. Kept
# in sync manually — there are two of these because the frontend needs a
# same-process fallback for SSR while the backend needs a seed value here.
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
        "en": "Scottish Charters and the Emergence of Government, 1100–1250",
        "fr": "Les chartes écossaises et l'émergence du gouvernement, 1100–1250",
    },
    "footerFunded": {
        "en": "Funded by the Arts and Humanities Research Council (AHRC).",
        "fr": "Financé par le Arts and Humanities Research Council (AHRC).",
    },
    "footerCopyright": {
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


def seed_labels(apps, schema_editor):
    SiteLabels = apps.get_model("common", "SiteLabels")
    if SiteLabels.objects.filter(pk=1).exists():
        return
    SiteLabels.objects.create(pk=1, labels=DEFAULT_LABELS)


def unseed_labels(apps, schema_editor):
    SiteLabels = apps.get_model("common", "SiteLabels")
    SiteLabels.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0008_sitelabels"),
    ]

    operations = [
        migrations.RunPython(seed_labels, unseed_labels),
    ]
