"""Tests for the IIIF Content Search 2.0 service (search-within manifest regions)."""

import pytest

from apps.annotations.models import Graph
from apps.iiif_presentation.content_search import build_content_search
from apps.iiif_presentation.manifest import build_manifest
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db

POLY = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[10, 20], [110, 20], [110, 70], [10, 70], [10, 20]]]},
}


def _stub_dims(_identifier):
    return (4000, 6000)


def _make(content: str, *, language: str = "la"):
    image = ItemImageFactory(locus="fol. 1r")
    graph = Graph.objects.create(item_image=image, annotation=POLY, annotation_type="text")
    text = ImageText.objects.create(
        item_image=image,
        content=content.format(gid=graph.id),
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language=language,
    )
    return image, graph, text


def test_search_returns_matching_region_with_iiif_coords():
    image, graph, text = _make('<p><seg corresp="#gid-{gid}">William king of Scots</seg></p>')
    page = build_content_search(
        image.item_part,
        images=[image],
        texts_by_image={image.id: [text]},
        graph_lookup={graph.id: graph},
        query="william",
        base_url="http://x",
        dims=_stub_dims,
    )
    assert page["type"] == "AnnotationPage"
    assert page["@context"] == "http://iiif.io/api/search/2/context.json"
    assert len(page["items"]) == 1
    hit = page["items"][0]
    assert hit["motivation"] == "highlighting"
    assert hit["body"]["value"] == "William king of Scots"
    # Same Y-flip the manifest uses: legacy y=20..70 on a 6000px image → top 5930.
    assert hit["target"] == f"http://x/api/v1/iiif/canvas/{image.id}#xywh=10,5930,100,50"


def test_search_is_case_insensitive_substring():
    image, graph, text = _make('<p><seg corresp="#gid-{gid}">Willelmus rex Scottorum</seg></p>')
    page = build_content_search(
        image.item_part,
        images=[image],
        texts_by_image={image.id: [text]},
        graph_lookup={graph.id: graph},
        query="REX",
        base_url="http://x",
        dims=_stub_dims,
    )
    assert len(page["items"]) == 1


def test_search_no_match_returns_empty_items():
    image, graph, text = _make('<p><seg corresp="#gid-{gid}">Omnibus</seg></p>')
    page = build_content_search(
        image.item_part,
        images=[image],
        texts_by_image={image.id: [text]},
        graph_lookup={graph.id: graph},
        query="william",
        base_url="http://x",
        dims=_stub_dims,
    )
    assert page["items"] == []


def test_search_empty_query_returns_empty_page():
    image, graph, text = _make('<p><seg corresp="#gid-{gid}">William</seg></p>')
    page = build_content_search(
        image.item_part,
        images=[image],
        texts_by_image={image.id: [text]},
        graph_lookup={graph.id: graph},
        query="   ",
        base_url="http://x",
        dims=_stub_dims,
    )
    assert page["items"] == []
    assert page["type"] == "AnnotationPage"


def test_search_endpoint(api_client):
    image, _graph, _text = _make('<p><seg corresp="#gid-{gid}">William</seg></p>')
    res = api_client.get(f"/api/v1/iiif/item-parts/{image.item_part_id}/search?q=william")
    assert res.status_code == 200
    assert res.data["type"] == "AnnotationPage"


def test_manifest_advertises_search_service():
    image = ItemImageFactory()
    manifest = build_manifest(
        image.item_part,
        images=[image],
        texts_by_image={},
        graph_lookup={},
        base_url="http://x",
        dims=_stub_dims,
    )
    service = manifest["service"][0]
    assert service["type"] == "SearchService2"
    assert service["id"] == f"http://x/api/v1/iiif/item-parts/{image.item_part.id}/search"
