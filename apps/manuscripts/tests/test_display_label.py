"""A part's display label is one string, the same on every surface that shows it."""

import pytest

from apps.manuscripts.tests.factories import (
    BibliographicSourceFactory,
    CatalogueNumberFactory,
    CurrentItemFactory,
    HistoricalItemFactory,
    ItemImageFactory,
    ItemPartFactory,
    RepositoryFactory,
)
from apps.search.documents.item_images import build_item_image_document
from apps.search.documents.item_parts import build_item_part_document

pytestmark = pytest.mark.django_db


def _shelved(locus):
    current_item = CurrentItemFactory(repository=RepositoryFactory(label="NRS"), shelfmark="GD 55/1")
    return ItemPartFactory(current_item=current_item, current_item_locus=locus)


def _catalogued(*numbers):
    part = ItemPartFactory(current_item=None, historical_item=HistoricalItemFactory(type="charter"))
    for number in numbers:
        CatalogueNumberFactory(
            historical_item=part.historical_item, catalogue=BibliographicSourceFactory(label="RRS"), number=number
        )
    return part


@pytest.mark.parametrize(
    ("make_part", "expected"),
    [
        (lambda: ItemPartFactory(custom_label="Fragment A"), "Fragment A"),
        (lambda: _shelved("fol. 2"), "NRS GD 55/1 fol. 2"),
        (lambda: _shelved(""), "NRS GD 55/1"),
        (lambda: _catalogued("236"), "Charter RRS 236"),
        (lambda: _catalogued(), "Charter"),
    ],
    ids=["custom label", "shelfmark and locus", "shelfmark without locus", "type and number", "type alone"],
)
def test_rest_search_and_iiif_show_the_same_label(api_client, make_part, expected):
    part = make_part()
    image = ItemImageFactory(item_part=part)

    rest = api_client.get(f"/api/v1/manuscripts/item-parts/{part.pk}/")
    manifest = api_client.get(f"/api/v1/iiif/item-parts/{part.pk}/manifest")

    assert rest.status_code == 200, rest.content
    assert manifest.status_code == 200, manifest.content
    assert {
        "rest": rest.data["display_label"],
        "item-parts index": build_item_part_document(part)["display_label"],
        "item-images index": build_item_image_document(image)["display_label"],
        "iiif manifest": manifest.data["label"]["none"][0],
    } == dict.fromkeys(["rest", "item-parts index", "item-images index", "iiif manifest"], expected)
