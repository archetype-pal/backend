"""Tests for the W3C Web Annotation converters + endpoints (Track C1)."""

import pytest

from apps.annotations.models import Graph
from apps.annotations_w3c.converters import graph_to_w3c, imagetext_to_w3c
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db

POLYGON = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[10, 20], [110, 20], [110, 70], [10, 70], [10, 20]]]},
    "properties": {"elementid": {"refs": [{"text": "salutem", "type": "salutation", "element": "seg"}]}},
}


def _text_graph(image):
    return Graph.objects.create(item_image=image, annotation=POLYGON, annotation_type="text")


def test_graph_to_w3c_text_region():
    image = ItemImageFactory()
    graph = _text_graph(image)
    doc = graph_to_w3c(graph, base_url="http://x")

    assert doc["type"] == "Annotation"
    assert doc["motivation"] == "identifying"
    assert doc["id"].endswith(f"/graphs/{graph.id}/")
    selectors = {s["type"] for s in doc["target"]["selector"]}
    assert selectors == {"FragmentSelector", "SvgSelector"}
    frag = next(s for s in doc["target"]["selector"] if s["type"] == "FragmentSelector")
    assert frag["value"] == "xywh=10,20,100,50"
    # H.5 reverse-link text surfaces as a transcribing body.
    assert any(b.get("value") == "salutem" for b in doc["body"])


def test_graph_to_w3c_flips_y_when_image_height_given():
    image = ItemImageFactory()
    graph = _text_graph(image)
    doc = graph_to_w3c(graph, base_url="http://x", image_height=1000)
    frag = next(s for s in doc["target"]["selector"] if s["type"] == "FragmentSelector")
    # legacy y=20..70 on a 1000px image → flipped top = 1000-70 = 930, h=50
    assert frag["value"] == "xywh=10,930,100,50"


def test_graph_to_w3c_motivation_by_type():
    image = ItemImageFactory()
    g = Graph.objects.create(item_image=image, annotation=POLYGON, annotation_type="editorial", note="hi")
    doc = graph_to_w3c(g)
    assert doc["motivation"] == "commenting"
    assert any(b["value"] == "hi" for b in doc["body"])


def test_imagetext_to_w3c_page():
    image = ItemImageFactory()
    graph = _text_graph(image)
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg type="salutation" corresp="#gid-{graph.id}">salutem</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
    )
    doc = imagetext_to_w3c(text, graph_lookup={graph.id: graph}, base_url="http://x")

    assert doc["type"] == "AnnotationPage"
    assert len(doc["items"]) == 1
    item = doc["items"][0]
    # text anchor + image region targets
    types = [
        t.get("selector", {}).get("type") if isinstance(t.get("selector"), dict) else "image" for t in item["target"]
    ]
    assert "TextQuoteSelector" in types
    text_target = next(t for t in item["target"] if isinstance(t.get("selector"), dict))
    assert text_target["selector"]["exact"] == "salutem"


def test_graph_endpoint(api_client):
    image = ItemImageFactory()
    graph = _text_graph(image)
    res = api_client.get(f"/api/v1/annotations-w3c/graphs/{graph.id}/")
    assert res.status_code == 200
    assert res.data["type"] == "Annotation"
    assert res.data["@context"] == "http://www.w3.org/ns/anno.jsonld"


def test_image_text_page_endpoint_hides_draft_from_anon(api_client):
    image = ItemImageFactory()
    graph = _text_graph(image)
    draft = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg corresp="#gid-{graph.id}">x</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    assert api_client.get(f"/api/v1/annotations-w3c/image-texts/{draft.id}/").status_code == 404
