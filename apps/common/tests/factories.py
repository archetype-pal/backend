import factory

from apps.common.models import Date, Place


class DateFactory(factory.django.DjangoModelFactory):
    date = "13 October 1245 X"
    min_weight = 1220
    max_weight = 1260

    class Meta:
        model = Date


class PlaceFactory(factory.django.DjangoModelFactory):
    # Unique: Place.name has a case-insensitive unique constraint, and two
    # random Faker cities in one test collide often enough to flake CI.
    name = factory.Sequence(lambda n: f"Place {n}")

    class Meta:
        model = Place
