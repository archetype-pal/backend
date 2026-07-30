from django.db import migrations

# The 3 about pages used to be hardcoded Next.js routes. Titles came from
# next-intl (`about.about`, `about.historicalContext`, `about.accessibilityTitle`)
# and are hardcoded here to match those strings. Body content is seeded with a
# plain placeholder — deliberately NOT read from the `SiteLabels` singleton,
# so seeding is deterministic and doesn't depend on what a given environment's
# DB happens to contain. Edit the real body text via the Pages backoffice UI.
PLACEHOLDER_CONTENT = {"en": "<p>Content coming soon.</p>", "fr": "<p>Contenu à venir.</p>"}

LEGACY_ABOUT_PAGES = [
    {
        "slug": "about",
        "title": {"en": "About the Project", "fr": "À propos du projet"},
        "order": 1,
    },
    {
        "slug": "historical-context",
        "title": {"en": "Historical Context", "fr": "Contexte historique"},
        "order": 2,
    },
    {
        "slug": "accessibility",
        "title": {"en": "Accessibility Statement", "fr": "Déclaration d'accessibilité"},
        "order": 3,
    },
]


def seed_legacy_about_pages(apps, schema_editor):
    Page = apps.get_model("pages", "Page")

    for entry in LEGACY_ABOUT_PAGES:
        Page.objects.get_or_create(
            slug=entry["slug"],
            defaults={
                "title": entry["title"],
                "content": dict(PLACEHOLDER_CONTENT),
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
    ]

    operations = [
        migrations.RunPython(seed_legacy_about_pages, unseed_legacy_about_pages),
    ]
