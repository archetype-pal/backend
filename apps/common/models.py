from django.conf import settings
from django.db import models
from django.utils import timezone


class SoftDeleteModel(models.Model):
    """Trash support: a row with `deleted_at` set is trashed, not gone.

    Opt-in visibility — the default manager stays unfiltered (house pattern,
    mirrors `ImageTextQuerySet.visible_to`), so every read path that must hide
    trashed rows filters explicitly. A real `.delete()` (purge) still works and
    still fires the model's delete signals.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True

    def soft_delete(self, user=None) -> None:
        self.deleted_at = timezone.now()
        self.deleted_by = user if getattr(user, "is_authenticated", False) else None
        self.save(update_fields=["deleted_at", "deleted_by"])

    def restore(self) -> None:
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["deleted_at", "deleted_by"])


class Date(models.Model):
    date = models.CharField(max_length=100)
    # Use the following two fields to represent the date as a numeric value
    #   This way, it can be used for sorting.
    min_weight = models.IntegerField(verbose_name="Minimum weight", help_text="The lower bound of the date range")
    max_weight = models.IntegerField(verbose_name="Maximum weight", help_text="The upper bound of the date range")

    def __str__(self):
        return self.date

    class Meta:
        verbose_name = "Date"
        ordering = ["date"]


class SiteLabel(models.Model):
    """Per-key store for customizable UI label translations.

    One row per label key, replacing the old `SiteLabels` singleton (a single
    JSONField blob on a fixed pk=1 row). `value` is a dict keyed by language
    code, e.g. {"en": "...", "fr": "..."}, mirroring `apps.pages.Page`'s
    `title`/`content` convention.
    """

    class Key(models.TextChoices):
        HISTORICAL_ITEM = "historicalItem", "Historical Item"
        CATALOGUE_NUMBER = "catalogueNumber", "Catalogue Number"
        POSITION = "position", "Position"
        DATE = "date", "Date"
        APP_MANUSCRIPTS = "appManuscripts", "App Name: Manuscripts"
        FIELD_HAIR_TYPE = "fieldHairType", "Field: Hair Type"
        FIELD_SHELFMARK = "fieldShelfmark", "Field: Shelfmark"
        FIELD_DATE_MIN_WEIGHT = "fieldDateMinWeight", "Field: Date Min Weight"
        FIELD_DATE_MAX_WEIGHT = "fieldDateMaxWeight", "Field: Date Max Weight"
        SEARCH_CATEGORY_IMAGES = "searchCategoryImages", "Search Category: Images"
        SEARCH_CATEGORY_SCRIBES = "searchCategoryScribes", "Search Category: Scribes"
        SEARCH_CATEGORY_HANDS = "searchCategoryHands", "Search Category: Hands"
        SEARCH_CATEGORY_GRAPHS = "searchCategoryGraphs", "Search Category: Graphs"
        SEARCH_CATEGORY_TEXTS = "searchCategoryTexts", "Search Category: Texts"
        SEARCH_CATEGORY_CLAUSES = "searchCategoryClauses", "Search Category: Clauses"
        SEARCH_CATEGORY_PEOPLE = "searchCategoryPeople", "Search Category: People"
        SEARCH_CATEGORY_PLACES = "searchCategoryPlaces", "Search Category: Places"
        SITE_TITLE = "siteTitle", "Site Title"
        SITE_TAGLINE = "siteTagline", "Site Tagline"
        FOOTER_LINE_1 = "footerLine1", "Footer Line 1"
        FOOTER_LINE_2 = "footerLine2", "Footer Line 2"
        FOOTER_BOTTOM_LINE = "footerBottomLine", "Footer Bottom Line"

    key = models.CharField(max_length=64, unique=True, choices=Key.choices)
    value = models.JSONField(default=dict, blank=True, help_text='Value per language, e.g. {"en": "...", "fr": "..."}')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]
        verbose_name = "Site Label"
        verbose_name_plural = "Site Labels"

    def __str__(self) -> str:
        return str(self.key)


class EditEvent(models.Model):
    """Append-only audit log for editor changes (M5.2).

    The viewer / editor surfaces show "X changed Y at Z"; review workflows
    surface "what changed since last week". The log is decoupled from any one
    domain table so we can track ImageText / Graph / etc. behind a single tab.
    """

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"
        STATUS_CHANGED = "status_changed", "Status changed"
        COMMENTED = "commented", "Commented"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="edit_events",
    )
    action = models.CharField(max_length=24, choices=Action.choices)
    # No single-column index: the (target_type, target_id) composite below
    # already covers target_type as its leftmost prefix.
    target_type = models.CharField(max_length=64)  # "graph", "imagetext", …
    target_id = models.BigIntegerField(db_index=True)
    summary = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="editevent_target_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}#{self.target_id} by {self.actor_id} @ {self.created}"
