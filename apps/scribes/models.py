from django.db import models


class Scribe(models.Model):
    name = models.CharField(max_length=100)
    period = models.ForeignKey("common.Date", on_delete=models.PROTECT, null=True, blank=True)
    scriptorium = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_placeholder(self) -> bool:
        """Whether this is the DigiPal import's stand-in for "no scribe".

        The import filed every hand it could not attribute under one made-up
        scribe, pk -1, "[name] update records relations later". The public site
        hides it, as it hides the import's placeholder item part (pk -1), and
        shows its hands as having no scribe. The backoffice still lists it, so
        editors can reassign those hands.
        """
        return self.pk is not None and self.pk < 1


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
    display_order = models.PositiveIntegerField(
        default=1,
        verbose_name="Display order",
        help_text="Where this hand comes among its part's hands; lower comes first, and the first is the "
        "viewer's default for a new annotation.",
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
        ordering = ["item_part", "display_order", "name", "id"]

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
