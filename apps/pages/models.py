from django.core.exceptions import ValidationError
from django.db import models

# Slugs served by static Next.js routes under app/(site)/about/ that a
# DB-backed Page must not shadow. Empty now that the 3 former built-in about
# pages (accessibility, historical-context, about-models-of-authority) have
# themselves been migrated into this Page table — see
# apps/pages/migrations/0002_seed_legacy_about_pages.py.
RESERVED_SLUGS = set()


class Page(models.Model):
    """Admin-authored content page, shown in the About menu and sidebar.

    `title` and `content` are JSON dicts keyed by language code (e.g.
    {"en": "...", "fr": "..."}), mirroring the `SiteLabels.labels` convention
    used for the site's other translatable content.
    """

    class Status(models.TextChoices):
        DRAFT = "Draft"
        PUBLISHED = "Published"

    slug = models.SlugField(max_length=150, unique=True)
    title = models.JSONField(default=dict, blank=True, help_text='Title per language, e.g. {"en": "...", "fr": "..."}')
    content = models.JSONField(
        default=dict, blank=True, help_text='HTML content per language, e.g. {"en": "...", "fr": "..."}'
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    order = models.PositiveIntegerField(default=0, db_index=True, help_text="Ordering within the About sidebar/menu.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-created_at"]

    def __str__(self) -> str:
        return self.title.get("en") or self.title.get("fr") or self.slug

    def clean(self):
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({"slug": f"'{self.slug}' is reserved for a built-in about page."})
