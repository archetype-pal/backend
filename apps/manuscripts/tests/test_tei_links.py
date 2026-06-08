"""Tests for text↔region link helpers + the regions endpoint (Phase 1)."""

import pytest

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import (
    add_graph_ref,
    linkable_element_count,
    parse_graph_refs,
    referenced_graph_ids,
    remove_graph_ref,
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


def test_linkable_element_count():
    # TEI sample: seg(address) + persName + seg(plain) = 3 linkable elements
    assert linkable_element_count(TEI) == 3
    assert linkable_element_count("<p>plain</p>") == 0


def test_add_graph_ref_preserves_camelcase_endtags():
    # HTMLParser lowercases tags; the rewriter must keep persName camelCase.
    content = "<p><persName>A</persName><seg>B</seg></p>"
    out = add_graph_ref(content, 1, 9)
    assert "</persName>" in out and "</seg>" in out
    assert "persname" not in out


def test_add_graph_ref_to_unlinked_element():
    content = '<p><seg type="address">Alpha</seg><persName type="name">John</persName></p>'
    out = add_graph_ref(content, 1, 77)
    assert out == ('<p><seg type="address">Alpha</seg><persName type="name" corresp="#gid-77">John</persName></p>')


def test_add_graph_ref_merges_into_existing_corresp():
    content = '<p><seg type="address" corresp="#gid-12">Alpha</seg></p>'
    out = add_graph_ref(content, 0, 34)
    assert 'corresp="#gid-12 #gid-34"' in out


def test_add_graph_ref_legacy_span():
    content = '<p><span data-dpt="clause" data-dpt-type="address">Alpha</span></p>'
    out = add_graph_ref(content, 0, 5)
    assert 'data-graph-id="5"' in out


def test_add_graph_ref_out_of_range():
    import pytest as _pytest

    with _pytest.raises(IndexError):
        add_graph_ref("<p><seg>x</seg></p>", 9, 1)


def test_remove_graph_ref_drops_sole_corresp_attribute():
    content = '<p><seg type="address" corresp="#gid-12">Alpha</seg></p>'
    out = remove_graph_ref(content, 12)
    assert out == '<p><seg type="address">Alpha</seg></p>'


def test_remove_graph_ref_keeps_other_tokens():
    out = remove_graph_ref(TEI, 88)
    assert 'corresp="#gid-99"' in out
    assert "gid-88" not in out
    # Unrelated refs untouched.
    assert 'corresp="#gid-12"' in out


def test_remove_graph_ref_legacy_data_graph_id():
    out = remove_graph_ref(DPT, 12)
    assert 'data-graph-id="34"' in out
    out_all = remove_graph_ref(DPT, 34)
    out_all = remove_graph_ref(out_all, 12)
    assert "data-graph-id" not in out_all


def test_remove_graph_ref_idempotent_when_absent():
    assert remove_graph_ref(TEI, 777) == TEI


def test_remove_graph_ref_preserves_camelcase():
    out = remove_graph_ref(TEI, 88)
    assert "</persName>" in out and "persname" not in out


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


@pytest.mark.django_db
def test_link_region_endpoint_creates_graph_and_ref(management_client):
    image = ItemImageFactory()
    text = ImageText.objects.create(
        item_image=image,
        content='<p><seg type="address">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    geometry = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]}}

    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/link-region/",
        {"element_index": 0, "geometry": geometry},
        format="json",
    )
    assert res.status_code == 201
    gid = res.data["graph_id"]
    graph = Graph.objects.get(id=gid)
    assert graph.annotation_type == "text"
    assert graph.item_image_id == image.id
    text.refresh_from_db()
    assert f'corresp="#gid-{gid}"' in text.content


@pytest.mark.django_db
def test_unlink_region_deletes_graph_and_strips_ref(management_client):
    image = ItemImageFactory()
    graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="text",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg type="address" corresp="#gid-{graph.id}">Alpha</seg><seg type="name">Beta</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-region/",
        {"graph_id": graph.id},
        format="json",
    )
    assert res.status_code == 200
    assert f"gid-{graph.id}" not in res.data["content"]
    assert not Graph.objects.filter(id=graph.id).exists()
    text.refresh_from_db()
    assert "corresp" not in text.content


@pytest.mark.django_db
def test_unlink_region_requires_graph_id(management_client):
    image = ItemImageFactory()
    text = ImageText.objects.create(
        item_image=image,
        content="<p><seg>Alpha</seg></p>",
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-region/",
        {},
        format="json",
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_unlink_region_requires_superuser(authenticated_client):
    image = ItemImageFactory()
    text = ImageText.objects.create(
        item_image=image,
        content="<p><seg>Alpha</seg></p>",
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    res = authenticated_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-region/",
        {"graph_id": 1},
        format="json",
    )
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_link_region_requires_superuser(authenticated_client):
    image = ItemImageFactory()
    text = ImageText.objects.create(
        item_image=image,
        content='<p><seg type="address">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    res = authenticated_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/link-region/",
        {"element_index": 0, "geometry": {"type": "Feature"}},
        format="json",
    )
    assert res.status_code in (401, 403)
