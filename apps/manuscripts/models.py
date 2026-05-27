from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from djiiif import IIIFField
import tagulous.models


class ItemFormat(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Repository(models.Model):
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=30)
    place = models.CharField(max_length=50, blank=True)
    url = models.URLField(null=True, blank=True)
    type = models.CharField(max_length=30, choices=[(c.lower(), c) for c in settings.REPOSITORY_TYPES], null=True)

    def __str__(self):
        return self.label

    class Meta:
        verbose_name_plural = "Repositories"
        ordering = ["name"]


class BibliographicSource(models.Model):
    """Used for citations of catalogues and manuscript descriptions"""

    name = models.CharField(max_length=200)
    label = models.CharField(max_length=100, help_text="A shorthand for the reference (e.g. BL)")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CurrentItem(models.Model):
    description = models.TextField(blank=True)
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE)
    shelfmark = models.CharField("Shelfmark", max_length=60)

    class Meta:
        ordering = ["repository", "shelfmark"]

    def __str__(self):
        return f"{self.repository.label} {self.shelfmark}"


class HistoricalItem(models.Model):
    type = models.CharField(
        max_length=20,
        choices=[(c.lower(), c) for c in settings.HISTORICAL_ITEM_TYPES],
    )
    format = models.ForeignKey(ItemFormat, null=True, blank=True, on_delete=models.SET_NULL)
    language = models.CharField(max_length=100, null=True, blank=True)

    hair_type = models.CharField(
        "Hair Type",
        max_length=20,
        choices=[(c.lower(), c) for c in settings.HISTORICAL_ITEM_HAIR_TYPES],
        null=True,
        blank=True,
    )

    date = models.ForeignKey("common.Date", on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        verbose_name = "Historical Item"
        ordering = ["id"]

    def get_catalogue_numbers_display(self):
        return ", ".join([cn.number for cn in self.catalogue_numbers.all()])

    def get_date_assessment(self):
        if not self.date_id:
            return None

        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("date_assessments")
        if prefetched is not None:
            return next((assessment for assessment in prefetched if assessment.date_id == self.date_id), None)

        return self.date_assessments.filter(date_id=self.date_id).first()

    def __str__(self):
        return f"{self.get_type_display()} {self.get_catalogue_numbers_display()}"


class HistoricalItemDateAssessment(models.Model):
    historical_item = models.ForeignKey(
        HistoricalItem,
        verbose_name=HistoricalItem._meta.verbose_name,
        related_name="date_assessments",
        on_delete=models.CASCADE,
    )
    date = models.ForeignKey(
        "common.Date",
        related_name="historical_item_assessments",
        on_delete=models.CASCADE,
    )
    probable_text_date = models.CharField(max_length=100, blank=True, default="")
    dating_notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Date Assessment"
        ordering = ["historical_item", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["historical_item", "date"],
                name="historical_item_date_assessment_unique",
            ),
        ]

    def clean(self):
        super().clean()
        if self.historical_item_id and self.date_id and self.historical_item.date_id != self.date_id:
            raise ValidationError(
                {"date": ("Date assessment date must match the date assigned to the historical item.")}
            )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.historical_item} - {self.date}"


class HistoricalItemDescription(models.Model):
    historical_item = models.ForeignKey(
        HistoricalItem,
        verbose_name=HistoricalItem._meta.verbose_name,
        related_name="descriptions",
        on_delete=models.CASCADE,
    )
    source = models.ForeignKey("BibliographicSource", on_delete=models.CASCADE)
    content = models.TextField()

    class Meta:
        verbose_name = "Description"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.source} - {self.historical_item}"


class ItemPart(models.Model):
    historical_item = models.ForeignKey(
        HistoricalItem, verbose_name=HistoricalItem._meta.verbose_name, on_delete=models.CASCADE
    )
    custom_label = models.CharField(
        max_length=80,
        default="",
        blank=True,
        help_text="A custom label for this part. If blank the shelfmark will be used as a label.",
    )
    current_item = models.ForeignKey(CurrentItem, null=True, blank=True, on_delete=models.SET_NULL)
    current_item_locus = models.CharField(
        "Locus", max_length=30, blank=True, default="", help_text="the location of this part in the Current Item"
    )

    class Meta:
        ordering = ["id"]

    def display_label(self) -> str:
        if self.custom_label:
            return str(self.custom_label)
        if self.current_item:
            return f"{self.current_item} {self.current_item_locus}"

        return str(self.historical_item)

    def __str__(self) -> str:
        return self.display_label()


class CatalogueNumber(models.Model):
    historical_item = models.ForeignKey(
        HistoricalItem,
        verbose_name=HistoricalItem._meta.verbose_name,
        related_name="catalogue_numbers",
        on_delete=models.CASCADE,
    )
    number = models.CharField(max_length=30)
    catalogue = models.ForeignKey("BibliographicSource", on_delete=models.CASCADE)
    url = models.URLField(null=True)

    class Meta:
        verbose_name = "Catalogue Number"
        ordering = ["number"]

    def __str__(self):
        return f"{self.catalogue.label} {self.number}"


class ItemImage(models.Model):
    item_part = models.ForeignKey(ItemPart, related_name="images", on_delete=models.CASCADE)
    image = IIIFField(max_length=200, upload_to="historical_items")
    locus = models.CharField(max_length=72, blank=True, default="")
    tags = tagulous.models.TagField(force_lowercase=True, blank=True)

    class Meta:
        ordering = ["item_part", "locus"]

    def number_of_annotations(self):
        return self.graphs.count()

    def number_of_image_annotations(self):
        return self.graphs.filter(annotation_type="image").count()

    def __str__(self) -> str:
        return f"{self.item_part} (locus: {self.locus})"


class ImageText(models.Model):
    class Type(models.TextChoices):
        TRANSCRIPTION = "Transcription"
        TRANSLATION = "Translation"

    class Status(models.TextChoices):
        DRAFT = "Draft"
        REVIEW = "Review"
        LIVE = "Live"
        REVIEWED = "Reviewed"

    item_image = models.ForeignKey(ItemImage, related_name="texts", on_delete=models.CASCADE)
    content = models.TextField()
    type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    language = models.CharField(max_length=100, blank=True, default="")
    # Phase G — when an editor sends a draft to a reviewer, we record who
    # they nominated. Cleared when the row leaves Review (back to Draft
    # or onward to Live). Doesn't constrain who *can* approve — any
    # is_staff user can — but it makes the queue UI honest about who's
    # expected to look at it.
    review_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="image_texts_assigned_for_review",
    )
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    # Phase H — retains the original `data-dpt` HTML through the TEI migration
    # window so the cutover is reversible. Populated by `migrate_imagetext_to_tei`
    # before `content` is flipped to TEI; dropped after the retention window
    # (H.11). Null on rows not yet migrated.
    content_dpt_legacy = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["item_image", "type"],
                name="imagetext_one_per_kind_per_image",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item_image} - {self.get_type_display()}"


class StatusTransition(models.Model):
    """Phase G — audit log of every status change on an `ImageText`.

    Records the editorial-state transitions specifically (Draft → Review
    → Live → Reviewed) so the reviewer queue can show "who sent this for
    review when, with what note."
    """

    image_text = models.ForeignKey(ImageText, related_name="status_transitions", on_delete=models.CASCADE)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="status_transitions",
    )
    from_status = models.CharField(max_length=16, choices=ImageText.Status.choices)
    to_status = models.CharField(max_length=16, choices=ImageText.Status.choices)
    note = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
        indexes = [models.Index(fields=["image_text", "-created"])]

    def __str__(self) -> str:
        return f"#{self.pk} {self.image_text_id} {self.from_status}→{self.to_status} by user={self.actor_id}"
