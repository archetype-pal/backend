from django.db import models


class Scribe(models.Model):
    name = models.CharField(max_length=100)
    period = models.CharField(max_length=100, blank=True)
    scriptorium = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.name


class Script(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Hand(models.Model):
    scribe = models.ForeignKey(Scribe, on_delete=models.PROTECT)
    item_part = models.ForeignKey("manuscripts.ItemPart", on_delete=models.PROTECT)
    script = models.ForeignKey(Script, on_delete=models.PROTECT, null=True, blank=True)

    name = models.CharField(max_length=100)
    date = models.CharField(max_length=100, blank=True)
    place = models.CharField(max_length=100, blank=True)

    description = models.TextField()
    item_part_images = models.ManyToManyField(
        "manuscripts.ItemImage",
        related_name="hands",
        limit_choices_to=models.Q(item_part=models.F("item_part")),
        blank=True,
    )

    def __str__(self):
        return self.name
