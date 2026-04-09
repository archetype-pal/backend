from django.conf import settings
import factory

from apps.manuscripts.models import (
    BibliographicSource,
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    HistoricalItemDescription,
    ImageText,
    ItemFormat,
    ItemImage,
    ItemPart,
    Repository,
)


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


class BibliographicSourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BibliographicSource

    name = factory.Faker("sentence", nb_words=3)
    label = factory.Faker("word")


class CatalogueNumberFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CatalogueNumber

    historical_item = factory.SubFactory(HistoricalItemFactory)
    number = factory.Sequence(lambda n: f"Cat. {n}")
    catalogue = factory.SubFactory(BibliographicSourceFactory)


class HistoricalItemDescriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HistoricalItemDescription

    historical_item = factory.SubFactory(HistoricalItemFactory)
    source = factory.SubFactory(BibliographicSourceFactory)
    content = factory.Faker("paragraph")


class ItemImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItemImage

    item_part = factory.SubFactory(ItemPartFactory)
    image = factory.Faker("image_url")
    locus = factory.Faker("word")


class ImageTextFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImageText

    item_image = factory.SubFactory(ItemImageFactory)
    content = factory.Faker("paragraph")
    type = ImageText.Type.TRANSCRIPTION
    status = ImageText.Status.DRAFT
