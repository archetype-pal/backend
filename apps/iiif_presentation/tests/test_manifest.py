"""Tests for the IIIF Presentation 3.0 manifest builder + endpoint (Track C2)."""

import json

import pytest

from apps.annotations.models import Graph
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


def test_manifest_structure_with_transcription():
    image = ItemImageFactory(locus="fol. 1r")
    graph = Graph.objects.create(item_image=image, annotation=POLY, annotation_type="text")
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg type="address" corresp="#gid-{graph.id}">Omnibus</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
    )
    manifest = build_manifest(
        image.item_part,
        images=[image],
        texts_by_image={image.id: [text]},
        graph_lookup={graph.id: graph},
        base_url="http://x",
        dims=_stub_dims,
    )

    assert manifest["type"] == "Manifest"
    assert manifest["@context"] == "http://iiif.io/api/presentation/3/context.json"
    canvas = manifest["items"][0]
    assert canvas["type"] == "Canvas"
    assert (canvas["width"], canvas["height"]) == (4000, 6000)
    # painting annotation present
    painting = canvas["items"][0]["items"][0]
    assert painting["motivation"] == "painting"
    assert painting["body"]["type"] == "Image"
    assert painting["body"]["service"][0]["type"] == "ImageService3"
    # transcription supplement anchored to a region, Y-flipped to IIIF origin
    supplement = canvas["annotations"][0]["items"][0]
    assert supplement["motivation"] == "supplementing"
    assert supplement["body"]["value"] == "Omnibus"
    # legacy y=20..70 on a 6000px image → flipped top = 6000-70 = 5930, h=50
    assert supplement["target"] == f"{canvas['id']}#xywh=10,5930,100,50"


def test_manifest_omits_empty_language():
    image = ItemImageFactory()
    graph = Graph.objects.create(item_image=image, annotation=POLY, annotation_type="text")
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg corresp="#gid-{graph.id}">x</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="",
    )
    manifest = build_manifest(
        image.item_part,
        images=[image],
        texts_by_image={image.id: [text]},
        graph_lookup={graph.id: graph},
        base_url="http://x",
        dims=_stub_dims,
    )
    body = manifest["items"][0]["annotations"][0]["items"][0]["body"]
    assert "language" not in body  # never emit `"language": null`


def test_manifest_without_text_has_no_supplement():
    image = ItemImageFactory()
    manifest = build_manifest(
        image.item_part,
        images=[image],
        texts_by_image={},
        graph_lookup={},
        base_url="http://x",
        dims=_stub_dims,
    )
    canvas = manifest["items"][0]
    assert "annotations" not in canvas


def test_manifest_endpoint(api_client):
    image = ItemImageFactory()
    res = api_client.get(f"/api/v1/iiif/item-parts/{image.item_part_id}/manifest")
    assert res.status_code == 200
    assert res.data["type"] == "Manifest"
    assert len(res.data["items"]) >= 1


def test_manifest_endpoint_is_cors_open_to_any_origin(api_client):
    """Third-party viewers (Mirador, UV) fetch manifests cross-origin.

    Without a wildcard header the browser blocks the response and the viewer
    silently fails to load the resource, so pin the header explicitly.
    """
    image = ItemImageFactory()
    res = api_client.get(
        f"/api/v1/iiif/item-parts/{image.item_part_id}/manifest",
        HTTP_ORIGIN="https://projectmirador.org",
    )
    assert res.status_code == 200
    assert res["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize("path", ["manifest", "search"])
def test_iiif_endpoints_serve_json_to_a_browser_accept_header(api_client, path):
    """A browser's Accept header must not content-negotiate away the JSON-LD.

    With DRF's default renderer set the BrowsableAPIRenderer wins on
    `Accept: text/html,...` and returns an HTML page instead of the IIIF
    document — so a shared manifest link opened in a browser serves markup no
    viewer can read (and 500s outright when staticfiles are uncollected, since
    the browsable template's {% static %} raises under ManifestStaticFilesStorage).
    """
    image = ItemImageFactory()
    res = api_client.get(
        f"/api/v1/iiif/item-parts/{image.item_part_id}/{path}",
        HTTP_ACCEPT="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    )
    assert res.status_code == 200
    assert res["Content-Type"] == "application/ld+json"
    assert not res.content.lstrip().startswith(b"<")
    json.loads(res.content)  # parses as JSON, not an HTML page


def test_content_search_endpoint_is_cors_open_to_any_origin(api_client):
    image = ItemImageFactory()
    res = api_client.get(
        f"/api/v1/iiif/item-parts/{image.item_part_id}/search",
        {"q": "omnibus"},
        HTTP_ORIGIN="https://projectmirador.org",
    )
    assert res.status_code == 200
    assert res["Access-Control-Allow-Origin"] == "*"
