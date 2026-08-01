from django.core.exceptions import ValidationError
from django.db import models

# Next resolves static route segments before dynamic ones, so a Page slugged
# "new" is shadowed by the backoffice's own /backoffice/pages/new editor and
# could never be opened again. Mirrors RESERVED_PAGE_SLUGS in the frontend's
# lib/pages.ts, which only disables the control client-side.
RESERVED_SLUGS: set[str] = {"new", "_components"}


class Page(models.Model):
    """Admin-authored content page, shown in the About menu and sidebar.

    `title` and `content` are JSON dicts keyed by language code (e.g.
    {"en": "...", "fr": "..."}), mirroring the `SiteLabel.value` convention
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
    include_in_quick_link = models.BooleanField(
        default=False, help_text="Show this page as a quick link in the site footer."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-created_at"]

    def __str__(self) -> str:
        return str(self.title.get("en") or self.title.get("fr") or self.slug)

    def clean(self):
        if self.slug in RESERVED_SLUGS:
            raise ValidationError({"slug": f"'{self.slug}' is reserved for a built-in about page."})
