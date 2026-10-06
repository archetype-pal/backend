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
    hand = models.ForeignKey(Hand, related_name="descriptions", on_delete=models.CASCADE)
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
