# Write a factory class for the date model from apps.common.models
import factory

from apps.common.models import Date


class DateFactory(factory.django.DjangoModelFactory):
    date = "13 October 1245 X"
    min_weight = 1220
    max_weight = 1260

    class Meta:
        model = Date
