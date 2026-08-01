from django.db import migrations, models

# The 3 about pages used to be hardcoded Next.js routes. Titles came from
# next-intl (`about.about`, `about.historicalContext`, `about.accessibilityTitle`)
# and are hardcoded here to match those strings. Body content is seeded with a
# plain placeholder — edit the real body text via the Pages backoffice UI.
PLACEHOLDER_CONTENT = {"en": "<p>Content coming soon.</p>", "fr": "<p>Contenu à venir.</p>"}

# `about-models-of-authority` is the site's canonical About URL — the frontend
# footer links to it directly and there are no redirects. The two pages flagged
# for quick links are the ones that footer column used to hardcode; "Search
# Charters" is a static route, not a Page, so it has no row here.
LEGACY_ABOUT_PAGES = [
    {
        "slug": "about-models-of-authority",
        "title": {"en": "About the Project", "fr": "À propos du projet"},
        "order": 1,
        "include_in_quick_link": True,
    },
    {
        "slug": "historical-context",
        "title": {"en": "Historical Context", "fr": "Contexte historique"},
        "order": 2,
        "include_in_quick_link": False,
    },
    {
        "slug": "accessibility",
        "title": {"en": "Accessibility Statement", "fr": "Déclaration d'accessibilité"},
        "order": 3,
        "include_in_quick_link": True,
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
                "include_in_quick_link": entry["include_in_quick_link"],
            },
        )


def unseed_legacy_about_pages(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    Page.objects.filter(slug__in=[entry["slug"] for entry in LEGACY_ABOUT_PAGES]).delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Page",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=150, unique=True)),
                (
                    "title",
                    models.JSONField(
                        blank=True, default=dict, help_text='Title per language, e.g. {"en": "...", "fr": "..."}'
                    ),
                ),
                (
                    "content",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text='HTML content per language, e.g. {"en": "...", "fr": "..."}',
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("Draft", "Draft"), ("Published", "Published")], default="Draft", max_length=10
                    ),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        db_index=True, default=0, help_text="Ordering within the About sidebar/menu."
                    ),
                ),
                (
                    "include_in_quick_link",
                    models.BooleanField(default=False, help_text="Show this page as a quick link in the site footer."),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["order", "-created_at"],
            },
        ),
        migrations.RunPython(seed_legacy_about_pages, unseed_legacy_about_pages),
    ]
