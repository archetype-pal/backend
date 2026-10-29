"""A reindex must cost a bounded number of queries per batch, not one per document.

Every relation a builder reads is declared on its registration (`select_related`
/ `prefetch_related`); a builder that reaches for something undeclared shows up
here as a query count that grows with the number of rows.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.models import ImageText, MsDescArea
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.scribes.tests.factories import HandFactory, ScribeFactory
from apps.search.registry import INDEX_REGISTRY, get_queryset_for_index
from apps.search.types import IndexType


def _corpus(images: int) -> None:
    """`images` images, each with a hand, an image graph, a text region, two linked texts and a tagged image."""
    for i in range(images):
        image = ItemImageFactory()
        image.tags = f"tag{i}"
        image.save()
        hand = HandFactory(item_part=image.item_part)
        region = GraphFactory(item_image=image, hand=hand, allograph=None, annotation_type="text")
        GraphFactory(item_image=image, hand=hand)
        MsDescArea.objects.create(item_part=image.item_part, area="physDesc", is_published=True, content="<physDesc/>")
        ImageText.objects.create(
            item_image=image,
            type="Transcription",
            status="Live",
            language="la",
            content=(
                f'<p><seg type="address" corresp="#gid-{region.id}">Omnibus</seg> '
                f'<persName type="name">Will</persName> <placeName type="region">York</placeName></p>'
            ),
        )
        ImageText.objects.create(
            item_image=image,
            type="Translation",
            status="Live",
            language="en",
            content='<p><seg type="address">To all</seg> <persName type="name">William</persName></p>',
        )
    ScribeFactory.create_batch(images)


def _queries_to_build(index_type: IndexType) -> int:
    registration = INDEX_REGISTRY[index_type]
    with CaptureQueriesContext(connection) as ctx:
        for obj in get_queryset_for_index(index_type):
            registration.documents(obj)
    return len(ctx.captured_queries)


@pytest.mark.django_db
@pytest.mark.parametrize("index_type", list(IndexType))
def test_query_count_does_not_grow_with_the_corpus(index_type, settings):
    settings.SEARCH_AUTO_REINDEX = False
    _corpus(3)
    few = _queries_to_build(index_type)
    _corpus(3)
    many = _queries_to_build(index_type)
    assert many == few, f"{index_type.segment}: {few} queries for 3 images, {many} for 6 — a builder reads per row"
