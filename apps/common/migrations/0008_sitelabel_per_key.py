from django.db import migrations, models

# Mirrors DEFAULT_MODEL_LABELS in the frontend's lib/model-labels.ts. Kept in
# sync manually — there are two of these because the frontend needs a
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


def seed_labels(apps, schema_editor):
    SiteLabel = apps.get_model("common", "SiteLabel")

    for key, value in DEFAULT_LABELS.items():
        SiteLabel.objects.get_or_create(key=key, defaults={"value": value})


def unseed_labels(apps, schema_editor):
    SiteLabel = apps.get_model("common", "SiteLabel")
    SiteLabel.objects.filter(key__in=DEFAULT_LABELS).delete()


class Migration(migrations.Migration):

    # Collapses the SiteLabels singleton and its replacement into the end state.
    # None of these five ever shipped, so no environment holds the intermediate
    # blob model; `replaces` is here so a dev DB that already ran the chain
    # recognises this as applied instead of recreating the table.
    replaces = [
        ("common", "0008_sitelabels"),
        ("common", "0009_seed_sitelabels_defaults"),
        ("common", "0010_sitelabel"),
        ("common", "0011_migrate_sitelabels_data"),
        ("common", "0012_delete_sitelabels"),
    ]

    dependencies = [
        ("common", "0007_alter_editevent_target_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteLabel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "key",
                    models.CharField(
                        choices=[
                            ("historicalItem", "Historical Item"),
                            ("catalogueNumber", "Catalogue Number"),
                            ("position", "Position"),
                            ("date", "Date"),
                            ("appManuscripts", "App Name: Manuscripts"),
                            ("fieldHairType", "Field: Hair Type"),
                            ("fieldShelfmark", "Field: Shelfmark"),
                            ("fieldDateMinWeight", "Field: Date Min Weight"),
                            ("fieldDateMaxWeight", "Field: Date Max Weight"),
                            ("searchCategoryImages", "Search Category: Images"),
                            ("searchCategoryScribes", "Search Category: Scribes"),
                            ("searchCategoryHands", "Search Category: Hands"),
                            ("searchCategoryGraphs", "Search Category: Graphs"),
                            ("searchCategoryTexts", "Search Category: Texts"),
                            ("searchCategoryClauses", "Search Category: Clauses"),
                            ("searchCategoryPeople", "Search Category: People"),
                            ("searchCategoryPlaces", "Search Category: Places"),
                            ("siteTitle", "Site Title"),
                            ("siteTagline", "Site Tagline"),
                            ("footerLine1", "Footer Line 1"),
                            ("footerLine2", "Footer Line 2"),
                            ("footerBottomLine", "Footer Bottom Line"),
                        ],
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "value",
                    models.JSONField(
                        blank=True, default=dict, help_text='Value per language, e.g. {"en": "...", "fr": "..."}'
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Site Label",
                "verbose_name_plural": "Site Labels",
                "ordering": ["key"],
            },
        ),
        migrations.RunPython(seed_labels, unseed_labels),
    ]
