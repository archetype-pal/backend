import factory

from apps.common.models import Date, Place


class DateFactory(factory.django.DjangoModelFactory):
    date = "13 October 1245 X"
    min_weight = 1220
    max_weight = 1260

    class Meta:
        model = Date


class PlaceFactory(factory.django.DjangoModelFactory):
    name = factory.Faker("city")

    class Meta:
        model = Place
