from django.db import models


class Scribe(models.Model):
    name = models.CharField(max_length=100)
    period = models.ForeignKey("common.Date", on_delete=models.PROTECT, null=True, blank=True)
    scriptorium = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Script(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Hand(models.Model):
    scribe = models.ForeignKey(Scribe, on_delete=models.PROTECT)
    item_part = models.ForeignKey("manuscripts.ItemPart", on_delete=models.PROTECT)
    script = models.ForeignKey(Script, on_delete=models.PROTECT, null=True, blank=True)

    name = models.CharField(max_length=100)
    num = models.PositiveIntegerField(
        default=1,
        db_index=True,
        verbose_name="Display order",
        help_text="Legacy DigiPal hand display order. Lower values are shown first.",
    )
    priority = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Higher values make this hand preferred for default assignment.",
    )
    is_default = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Prefer this hand as the default assignment hand for its item/image.",
    )
    # SET_NULL, not CASCADE: `common.Date` is a shared lookup row; deleting one
    # must not delete the Hands that reference it. Matches HistoricalItem.date.
    date = models.ForeignKey("common.Date", on_delete=models.SET_NULL, null=True, blank=True)
    # SET_NULL, not CASCADE/PROTECT: `common.Place` is a shared authority-list
    # row; deleting one must not delete the Hands that reference it.
    place = models.ForeignKey("common.Place", on_delete=models.SET_NULL, null=True, blank=True, related_name="hands")

    item_part_images = models.ManyToManyField(
        "manuscripts.ItemImage",
        related_name="hands",
        blank=True,
    )

    class Meta:
        ordering = ["item_part", "-is_default", "-priority", "num", "name", "id"]

    def __str__(self):
        return self.name


class HandDescription(models.Model):
    """One of possibly several descriptions of a Hand, each optionally citing a source.

    Replaces the old single Hand.description field, which could hold only one
    description and couldn't record which source (if any) it came from.
    """

    hand = models.ForeignKey(Hand, related_name="descriptions", on_delete=models.CASCADE)
    # SET_NULL, not CASCADE like HistoricalItemDescription.source: not every
    # description has a known citation (e.g. free text folded in from the
    # old single-field migration), so source is optional here.
    source = models.ForeignKey(
        "manuscripts.BibliographicSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hand_descriptions",
    )
    content = models.TextField()

    class Meta:
        verbose_name = "Hand description"
        ordering = ["id"]

    def __str__(self):
        return f"{self.source} - {self.hand}" if self.source_id else str(self.hand)
