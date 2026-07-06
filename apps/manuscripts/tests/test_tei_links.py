"""Tests for text↔region link helpers + the regions endpoint (Phase 1)."""

import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import (
    add_graph_ref,
    linkable_element_count,
    parse_graph_refs,
    referenced_graph_ids,
    remove_graph_ref,
    remove_graph_ref_at,
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


# --- per-element unlink (remove_graph_ref_at) ---


def test_remove_graph_ref_at_strips_only_the_target_element():
    content = '<p><seg corresp="#gid-12">Alpha</seg><seg corresp="#gid-12 #gid-9">Beta</seg></p>'
    out = remove_graph_ref_at(content, 0, 12)
    # element 0 loses the ref; element 1 (also linked to 12) is untouched.
    assert out == '<p><seg>Alpha</seg><seg corresp="#gid-12 #gid-9">Beta</seg></p>'


def test_remove_graph_ref_at_keeps_other_tokens_on_the_element():
    out = remove_graph_ref_at('<persName corresp="#gid-88 #gid-99">John</persName>', 0, 88)
    assert 'corresp="#gid-99"' in out and "gid-88" not in out


def test_remove_graph_ref_at_noop_when_element_lacks_ref():
    content = '<p><seg corresp="#gid-12">Alpha</seg><seg>Beta</seg></p>'
    assert remove_graph_ref_at(content, 1, 12) == content


def test_remove_graph_ref_at_out_of_range_raises():
    with pytest.raises(IndexError):
        remove_graph_ref_at('<p><seg corresp="#gid-1">A</seg></p>', 5, 1)


def test_remove_graph_ref_at_legacy_span():
    assert 'data-graph-id="34"' in remove_graph_ref_at(DPT, 0, 12)


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
def test_unlink_element_removes_one_link_keeps_graph_and_siblings(management_client):
    image = ItemImageFactory()
    graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="text",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg corresp="#gid-{graph.id}">Alpha</seg><seg corresp="#gid-{graph.id}">Beta</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-element/",
        {"element_index": 0, "graph_id": graph.id},
        format="json",
    )
    assert res.status_code == 200
    text.refresh_from_db()
    # Only element 0 was unlinked; element 1 kept its ref; the region survives.
    assert text.content == f'<p><seg>Alpha</seg><seg corresp="#gid-{graph.id}">Beta</seg></p>'
    assert Graph.objects.filter(id=graph.id).exists()


@pytest.mark.django_db
def test_unlink_element_requires_superuser(authenticated_client):
    image = ItemImageFactory()
    text = ImageText.objects.create(
        item_image=image,
        content="<p><seg>A</seg></p>",
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    res = authenticated_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-element/",
        {"element_index": 0, "graph_id": 1},
        format="json",
    )
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_link_region_with_existing_graph_id_adds_ref_no_new_graph(management_client):
    # "Also link": one region graph linked to a transcription phrase AND its
    # translation phrase — a second corresp ref, not a second graph.
    image = ItemImageFactory()
    transcription = ImageText.objects.create(
        item_image=image,
        content='<p><seg type="address">Rex</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    translation = ImageText.objects.create(
        item_image=image,
        content='<p><seg type="address">King</seg></p>',
        type=ImageText.Type.TRANSLATION,
        status=ImageText.Status.DRAFT,
        language="en",
    )
    geometry = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]}}

    res1 = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{transcription.id}/link-region/",
        {"element_index": 0, "geometry": geometry},
        format="json",
    )
    assert res1.status_code == 201
    gid = res1.data["graph_id"]
    assert Graph.objects.filter(item_image=image, annotation_type="text").count() == 1

    res2 = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{translation.id}/link-region/",
        {"element_index": 0, "graph_id": gid},
        format="json",
    )
    # 200, not 201: linking an EXISTING region to another element creates no
    # new resource (only the new-region path above returns 201 Created).
    assert res2.status_code == 200
    assert res2.data["graph_id"] == gid
    # No NEW graph — the same region is referenced from both texts.
    assert Graph.objects.filter(item_image=image, annotation_type="text").count() == 1
    translation.refresh_from_db()
    assert f'corresp="#gid-{gid}"' in translation.content
    transcription.refresh_from_db()
    assert f'corresp="#gid-{gid}"' in transcription.content


@pytest.mark.django_db
def test_link_region_existing_graph_id_must_be_text_graph_of_image(management_client):
    image = ItemImageFactory()
    text = ImageText.objects.create(
        item_image=image,
        content="<p><seg>Rex</seg></p>",
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    glyph = GraphFactory(item_image=image, annotation_type="image")

    # a glyph graph isn't a text region
    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/link-region/",
        {"element_index": 0, "graph_id": glyph.id},
        format="json",
    )
    assert res.status_code == 400
    # a non-existent graph id
    res2 = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/link-region/",
        {"element_index": 0, "graph_id": 999999},
        format="json",
    )
    assert res2.status_code == 400


@pytest.mark.django_db
def test_deleting_text_graph_strips_corresp_invariant():
    # The pre_delete signal makes corresp-stripping an invariant of ANY text-graph
    # deletion (not just the unlink-region endpoint), so no client can orphan a ref.
    image = ItemImageFactory()
    graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="text",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg corresp="#gid-{graph.id}">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    graph.delete()

    text.refresh_from_db()
    assert f"gid-{graph.id}" not in text.content
    assert "corresp" not in text.content


@pytest.mark.django_db
def test_image_graph_delete_leaves_text_untouched():
    # Non-text graphs must not touch transcription content.
    image = ItemImageFactory()
    glyph = GraphFactory(item_image=image, annotation_type="image")
    text = ImageText.objects.create(
        item_image=image,
        content='<p><seg corresp="#gid-999">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    glyph.delete()

    text.refresh_from_db()
    assert text.content == '<p><seg corresp="#gid-999">Alpha</seg></p>'


@pytest.mark.django_db
def test_graph_viewer_write_delete_endpoint_strips_corresp(authenticated_client):
    # The HTTP delete path (e.g. backoffice / viewer write viewset) also strips
    # corresp via the signal — the dangling-corresp gap is closed server-side.
    image = ItemImageFactory()
    graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature"},
        annotation_type="text",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg corresp="#gid-{graph.id}">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    res = authenticated_client.delete(f"/api/v1/annotations/graphs/{graph.id}/")

    assert res.status_code in (200, 204)
    assert not Graph.objects.filter(id=graph.id).exists()
    text.refresh_from_db()
    assert f"gid-{graph.id}" not in text.content


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
