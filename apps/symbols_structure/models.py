from django.conf import settings
from django.db import models


class Character(models.Model):

    name = models.CharField(max_length=100)
    type = models.CharField(
        choices=[(c, c) for c in settings.CHARACTER_ITEM_TYPES], max_length=16, null=True, blank=True
    )

    def __str__(self):
        return self.name


class Allograph(models.Model):
    character = models.ForeignKey(Character, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    components = models.ManyToManyField(
        "Component", related_name="allographs", through="AllographComponent", blank=True
    )

    def __str__(self):
        return self.name


class Feature(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Component(models.Model):
    name = models.CharField(max_length=100, unique=True)
    features = models.ManyToManyField(Feature, related_name="components", blank=True)

    def __str__(self):
        return self.name


class AllographComponent(models.Model):
    allograph = models.ForeignKey(Allograph, on_delete=models.CASCADE)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)
    features = models.ManyToManyField(Feature, through="AllographComponentFeature")

    class Meta:
        unique_together = ("allograph", "component")


class AllographComponentFeature(models.Model):
    allograph_component = models.ForeignKey(AllographComponent, on_delete=models.CASCADE)
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE)
    set_by_default = models.BooleanField(default=False)

    class Meta:
        unique_together = ("allograph_component", "feature")


class Position(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = settings.MODEL_DISPLAY_NAME_POSITION

    def __str__(self):
        return self.name
