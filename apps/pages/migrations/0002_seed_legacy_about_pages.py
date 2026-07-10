from django.db import migrations

# The 3 about pages used to be hardcoded Next.js routes whose body HTML lived
# in the `SiteLabels` singleton (see apps/common/models.py). Titles were never
# stored there — they came from next-intl (`about.about`, `about.historicalContext`,
# `about.accessibilityTitle`) — so they're hardcoded here, mirroring those strings.
LEGACY_ABOUT_PAGES = [
    {
        "slug": "about-models-of-authority",
        "title": {"en": "About the Project", "fr": "À propos du projet"},
        "source_label_key": "pageAboutModelsOfAuthority",
        "order": 1,
    },
    {
        "slug": "historical-context",
        "title": {"en": "Historical Context", "fr": "Contexte historique"},
        "source_label_key": "pageHistoricalContext",
        "order": 2,
    },
    {
        "slug": "accessibility",
        "title": {"en": "Accessibility Statement", "fr": "Déclaration d'accessibilité"},
        "source_label_key": "pageAccessibility",
        "order": 3,
    },
]


def seed_legacy_about_pages(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    SiteLabels = apps.get_model("common", "SiteLabels")

    site_labels = SiteLabels.objects.filter(pk=1).first()
    labels = site_labels.labels if site_labels else {}

    for entry in LEGACY_ABOUT_PAGES:
        content = labels.get(entry["source_label_key"]) or {}
        Page.objects.get_or_create(
            slug=entry["slug"],
            defaults={
                "title": entry["title"],
                "content": {"en": content.get("en", ""), "fr": content.get("fr", "")},
                "status": "Published",
                "order": entry["order"],
            },
        )


def unseed_legacy_about_pages(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    Page.objects.filter(slug__in=[entry["slug"] for entry in LEGACY_ABOUT_PAGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0001_initial"),
        ("common", "0009_seed_sitelabels_defaults"),
    ]

    operations = [
        migrations.RunPython(seed_legacy_about_pages, unseed_legacy_about_pages),
    ]
