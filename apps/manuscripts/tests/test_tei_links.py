"""Tests for text↔region link helpers + the regions endpoint (Phase 1)."""

import pytest

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import (
    parse_graph_refs,
    referenced_graph_ids,
    rewrite_graph_refs,
)
from apps.manuscripts.tests.factories import ItemImageFactory

TEI = (
    '<p><seg type="address" corresp="#gid-12">Alpha</seg>'
    '<persName type="name" corresp="#gid-88 #gid-99">John</persName>'
    "<seg>plain</seg></p>"
)
DPT = '<p><span data-dpt="clause" data-dpt-type="address" data-graph-id="12,34">Alpha</span></p>'


def test_parse_graph_refs_tei():
    refs = parse_graph_refs(TEI)
    assert [r.graph_ids for r in refs] == [[12], [88, 99]]
    assert refs[0].element == "seg"
    assert refs[0].type == "address"
    assert refs[0].text == "Alpha"
    assert refs[1].text == "John"


def test_parse_graph_refs_legacy_dpt():
    refs = parse_graph_refs(DPT)
    assert refs[0].graph_ids == [12, 34]
    assert refs[0].type == "address"


def test_referenced_graph_ids_flattens():
    assert referenced_graph_ids(TEI) == {12, 88, 99}


def test_rewrite_graph_refs_tei_and_dpt():
    out = rewrite_graph_refs(TEI, {12: 500, 88: 800})
    assert 'corresp="#gid-500"' in out
    assert 'corresp="#gid-800 #gid-99"' in out
    out_dpt = rewrite_graph_refs(DPT, {34: 340})
    assert 'data-graph-id="12,340"' in out_dpt


def test_rewrite_leaves_unmapped_unchanged():
    assert rewrite_graph_refs(TEI, {}) == TEI


# --- regions endpoint ---

pytestmark_db = pytest.mark.django_db


@pytest.mark.django_db
def test_regions_endpoint_resolves_links(api_client):
    image = ItemImageFactory()
    text_graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="text",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg type="address" corresp="#gid-{text_graph.id}">Alpha</seg>'
        '<seg corresp="#gid-999999">dangling</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
    )

    res = api_client.get(f"/api/v1/manuscripts/image-texts/{text.id}/regions/")
    assert res.status_code == 200
    regions = {r["graph_id"]: r for r in res.data["regions"]}

    live = regions[text_graph.id]
    assert live["exists"] and live["is_text"] and live["same_image"]
    assert live["text"] == "Alpha"
    assert live["geometry"]["type"] == "Feature"

    dangling = regions[999999]
    assert dangling["exists"] is False
    assert dangling["geometry"] is None
