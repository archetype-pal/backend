from django.conf import settings
import factory

from apps.annotations.models import Graph
from apps.manuscripts.models import (
    BibliographicSource,
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    HistoricalItemDateAssessment,
    HistoricalItemDescription,
    ImageText,
    ItemFormat,
    ItemImage,
    ItemPart,
    MsDescArea,
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


class HistoricalItemDateAssessmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HistoricalItemDateAssessment

    historical_item = factory.SubFactory(HistoricalItemFactory)
    date = factory.SelfAttribute("historical_item.date")
    probable_text_date = factory.Faker("sentence", nb_words=4)
    dating_notes = factory.Faker("paragraph")


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


class MsDescAreaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MsDescArea

    item_part = factory.SubFactory(ItemPartFactory)
    area = MsDescArea.Area.PHYS_DESC
    content = "<physDesc><objectDesc form='codex'><p>Parchment codex.</p></objectDesc></physDesc>"


# A legacy data-dpt transcription as the DigiPal import left it; the TEI migration tests convert it.
LEGACY_DPT = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation" data-graph-id="2824">salutem</span></p>'
)


def live_text(content: str, **kwargs) -> ImageText:
    return ImageTextFactory(content=content, status=ImageText.Status.LIVE, language="la", **kwargs)


POLYGON = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}}


def text_region(image: ItemImage, *, annotation: dict | None = None, annotation_type: str = "text") -> Graph:
    """A text-region (or editorial) graph on `image`, with no allograph or hand."""
    graph: Graph = Graph.objects.create(
        item_image=image, annotation=POLYGON if annotation is None else annotation, annotation_type=annotation_type
    )
    return graph


def image_text(
    image: ItemImage,
    content: str,
    *,
    type: str = ImageText.Type.TRANSCRIPTION,  # noqa: A002
    status: str = ImageText.Status.DRAFT,
    language: str = "la",
    **extra,
) -> ImageText:
    """A Latin draft transcription of `image` holding `content`, unless told otherwise."""
    text: ImageText = ImageText.objects.create(
        item_image=image, content=content, type=type, status=status, language=language, **extra
    )
    return text


def catalogued_item_part():
    """A part with no current item, so `str(part)` falls back to its catalogue numbers."""
    part = ItemPartFactory(current_item=None)
    CatalogueNumberFactory(historical_item=part.historical_item)
    return part
