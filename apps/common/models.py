from django.conf import settings
from django.db import models


class Date(models.Model):
    date = models.CharField(max_length=100)
    # Use the following two fields to represent the date as a numeric value
    #   This way, it can be used for sorting.
    min_weight = models.IntegerField(
        verbose_name=settings.FIELD_DISPLAY_NAME_DATE_MIN_WEIGHT, help_text="The lower bound of the date range"
    )
    max_weight = models.IntegerField(
        verbose_name=settings.FIELD_DISPLAY_NAME_DATE_MAX_WEIGHT, help_text="The upper bound of the date range"
    )

    def __str__(self):
        return self.date

    def as_dict(self):
        return {
            "min_weight": self.min_weight,
            "max_weight": self.max_weight,
        }

    class Meta:
        verbose_name = settings.MODEL_DISPLAY_NAME_DATE
