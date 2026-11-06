"""One definition of a described graph (an image graph with at least one feature), and the
counts that a reader sees: glyphs only."""

import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphComponentFactory, GraphFactory
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.search.documents.item_images import build_item_image_document
from apps.search.quality import quality_cards
from apps.search.registry import get_queryset_for_index
from apps.search.types import IndexType
from apps.symbols_structure.tests.factories import FeatureFactory

pytestmark = pytest.mark.django_db


def _graphs():
    image = ItemImageFactory()
    described = GraphFactory(item_image=image)
    GraphComponentFactory(graph=described).features.add(FeatureFactory())
    components_only = GraphFactory(item_image=image)
    GraphComponentFactory(graph=components_only)
    bare = GraphFactory(item_image=image)
    region = GraphFactory(item_image=image, annotation_type=Graph.AnnotationType.TEXT, allograph=None, hand=None)
    note = GraphFactory(item_image=image, annotation_type=Graph.AnnotationType.EDITORIAL, allograph=None, hand=None)
    return image, described, components_only, bare, region, note


def test_only_an_image_graph_with_a_feature_is_described():
    _, described, components_only, bare, region, note = _graphs()

    assert [g.is_described() for g in (described, components_only, bare, region, note)] == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert set(Graph.objects.undescribed()) == {components_only, bare}


def test_the_quality_card_counts_undescribed_image_graphs():
    _graphs()

    card = next(card for card in quality_cards() if card["id"] == "undescribed-graphs")

    assert card["count"] == 2


def test_public_image_counts_are_glyphs(client):
    image, *_ = _graphs()

    response = client.get(f"/api/v1/manuscripts/item-images/{image.id}/")
    document = build_item_image_document(get_queryset_for_index(IndexType.ITEM_IMAGES).get(pk=image.pk))

    assert response.data["number_of_annotations"] == 3
    assert "number_of_image_annotations" not in response.data
    assert document["number_of_annotations"] == 3
