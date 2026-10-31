from django.core.validators import RegexValidator
from django.db import models

# Next resolves static route segments before dynamic ones, so a Page slugged
# "new" is shadowed by the backoffice's own /backoffice/pages/new editor and
# could never be opened again. Mirrors RESERVED_PAGE_SLUGS in the frontend's
# lib/pages.ts, which only disables the control client-side.
RESERVED_SLUGS: set[str] = {"new", "_components"}

# "about" is the built-in heading: a Page with no `menu_heading` sits under it,
# and the nav order already has an `about` entry, so a custom heading slugged
# "about" would be indistinguishable from it. "new" is the backoffice editor
# route, as for pages.
RESERVED_HEADING_SLUGS: set[str] = {"about", "new"}

# Lowercase only: the frontend recognises a `heading:<slug>` nav-order key with
# /^heading:[a-z0-9_-]+$/ (lib/site-features.ts), so a heading slugged "Help"
# would be dropped from the menu bar and the Site Features editor.
validate_heading_slug = RegexValidator(
    r"^[a-z0-9_-]+\Z", "Use only lowercase letters, numbers, hyphens and underscores."
)


class MenuHeading(models.Model):
    """Admin-created top-level navigation heading (e.g. "Help", "Events") that groups Pages.

    Its position in the main menu bar is stored in the site features'
    `sectionOrder` as `heading:<slug>`, next to the built-in sections, so
    `slug` cannot change after creation.
    """

    slug = models.SlugField(max_length=100, unique=True, validators=[validate_heading_slug])
    title = models.JSONField(default=dict, blank=True, help_text='Title per language, e.g. {"en": "...", "fr": "..."}')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return str(self.title.get("en") or self.title.get("fr") or self.slug)


class Page(models.Model):
    """Admin-authored content page, shown in a main-menu dropdown and its sidebar.

    `menu_heading` picks the dropdown: null means the built-in About menu.
    The public URL is `/about/{slug}` whatever the heading, so moving a page
    to another heading never breaks links to it.

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
    menu_heading = models.ForeignKey(
        MenuHeading,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pages",
        help_text="Main-menu heading the page is listed under; empty means About.",
    )
    order = models.PositiveIntegerField(
        default=0, db_index=True, help_text="Ordering within the page's menu heading and sidebar."
    )
    include_in_quick_link = models.BooleanField(
        default=False, help_text="Show this page as a quick link in the site footer."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-created_at"]

    def __str__(self) -> str:
        return str(self.title.get("en") or self.title.get("fr") or self.slug)
