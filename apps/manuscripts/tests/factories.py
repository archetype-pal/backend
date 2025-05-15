import factory
from django.conf import settings

from apps.manuscripts.models import CurrentItem, HistoricalItem, ItemFormat, ItemImage, ItemPart, Repository


class ItemFormatFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItemFormat

    name = factory.Faker("word")


class RepositoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Repository

    name = factory.Faker("word")
    label = factory.Faker("word")
    place = factory.Faker("city")
    url = factory.Faker("url")
    type = settings.REPOSITORY_TYPES[0]


class CurrentItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CurrentItem

    description = factory.Faker("sentence")
    repository = factory.SubFactory(RepositoryFactory)
    shelfmark = factory.Faker("word")


class HistoricalItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HistoricalItem

    type = settings.HISTORICAL_ITEM_TYPES[0]
    format = factory.SubFactory(ItemFormatFactory)
    language = factory.Faker("language_code")
    hair_type = settings.HISTORICAL_ITEM_HAIR_TYPES[0]
    date = factory.SubFactory("apps.common.tests.factories.DateFactory")


class ItemPartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItemPart

    historical_item = factory.SubFactory(HistoricalItemFactory)
    current_item = factory.SubFactory(CurrentItemFactory)


class ItemImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItemImage

    item_part = factory.SubFactory(ItemPartFactory)
    image = factory.Faker("image_url")
    locus = factory.Faker("word")
