"""Text↔region link helpers and the regions endpoint."""

import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.common.models import EditEvent
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import (
    add_graph_ref,
    parse_graph_refs,
    referenced_graph_ids,
    remove_graph_ref,
    remove_graph_ref_at,
)
from apps.manuscripts.tests.factories import ItemImageFactory

TEI = (
    '<p><seg type="address" corresp="#gid-12">Alpha</seg>'
    '<persName type="name" corresp="#gid-88 #gid-99">John</persName>'
    "<seg>plain</seg></p>"
)
DPT = '<p><span data-dpt="clause" data-dpt-type="address" data-graph-id="12,34">Alpha</span></p>'


def test_parse_graph_refs_reads_tei_and_legacy_markup():
    refs = parse_graph_refs(TEI)
    assert [(r.graph_ids, r.element, r.type, r.text) for r in refs] == [
        ([12], "seg", "address", "Alpha"),
        ([88, 99], "persname", "name", "John"),
    ]
    assert [(r.graph_ids, r.type) for r in parse_graph_refs(DPT)] == [([12, 34], "address")]
    assert referenced_graph_ids(TEI) == {12, 88, 99}


@pytest.mark.parametrize(
    ("content", "index", "graph_id", "expected"),
    [
        # A new ref on an unlinked element; HTMLParser lower-cases tags, so camelCase must be restored.
        (
            '<p><seg type="address">Alpha</seg><persName type="name">John</persName></p>',
            1,
            77,
            '<p><seg type="address">Alpha</seg><persName type="name" corresp="#gid-77">John</persName></p>',
        ),
        # Merged into an existing corresp.
        (
            '<p><seg type="address" corresp="#gid-12">Alpha</seg></p>',
            0,
            34,
            '<p><seg type="address" corresp="#gid-12 #gid-34">Alpha</seg></p>',
        ),
        # Legacy data-dpt span.
        (
            '<p><span data-dpt="clause" data-dpt-type="address">Alpha</span></p>',
            0,
            5,
            '<p><span data-dpt="clause" data-dpt-type="address" data-graph-id="5">Alpha</span></p>',
        ),
    ],
)
def test_add_graph_ref(content, index, graph_id, expected):
    assert add_graph_ref(content, index, graph_id) == expected


def test_add_graph_ref_out_of_range():
    with pytest.raises(IndexError):
        add_graph_ref("<p><seg>x</seg></p>", 9, 1)


@pytest.mark.parametrize(
    ("content", "graph_id", "expected"),
    [
        # The sole token: the attribute goes with it.
        ('<p><seg type="address" corresp="#gid-12">Alpha</seg></p>', 12, '<p><seg type="address">Alpha</seg></p>'),
        # One token of several, everywhere it appears; unrelated refs and camelCase survive.
        (
            TEI,
            88,
            '<p><seg type="address" corresp="#gid-12">Alpha</seg>'
            '<persName type="name" corresp="#gid-99">John</persName><seg>plain</seg></p>',
        ),
        (DPT, 12, '<p><span data-dpt="clause" data-dpt-type="address" data-graph-id="34">Alpha</span></p>'),
        # Absent: unchanged.
        (TEI, 777, TEI),
    ],
)
def test_remove_graph_ref(content, graph_id, expected):
    assert remove_graph_ref(content, graph_id) == expected


@pytest.mark.parametrize(
    ("content", "index", "graph_id", "expected"),
    [
        # Only the addressed element loses the ref; a sibling linked to the same region is untouched.
        (
            '<p><seg corresp="#gid-12">Alpha</seg><seg corresp="#gid-12 #gid-9">Beta</seg></p>',
            0,
            12,
            '<p><seg>Alpha</seg><seg corresp="#gid-12 #gid-9">Beta</seg></p>',
        ),
        ('<persName corresp="#gid-88 #gid-99">John</persName>', 0, 88, '<persName corresp="#gid-99">John</persName>'),
        # The element exists but does not carry the ref: a no-op.
        (
            '<p><seg corresp="#gid-12">Alpha</seg><seg>Beta</seg></p>',
            1,
            12,
            '<p><seg corresp="#gid-12">Alpha</seg><seg>Beta</seg></p>',
        ),
        (DPT, 0, 12, '<p><span data-dpt="clause" data-dpt-type="address" data-graph-id="34">Alpha</span></p>'),
    ],
)
def test_remove_graph_ref_at(content, index, graph_id, expected):
    assert remove_graph_ref_at(content, index, graph_id) == expected


def test_remove_graph_ref_at_out_of_range_raises():
    with pytest.raises(IndexError):
        remove_graph_ref_at('<p><seg corresp="#gid-1">A</seg></p>', 5, 1)


# --- regions endpoint ---


@pytest.mark.django_db
def test_regions_endpoint_resolves_links(api_client, authenticated_client):
    image = ItemImageFactory()
    text_graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="text",
    )
    editorial = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="editorial",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg type="address" corresp="#gid-{text_graph.id}">Alpha</seg>'
        '<seg corresp="#gid-999999">dangling</seg>'
        f'<seg corresp="#gid-{editorial.id}">Beta</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
    )

    url = f"/api/v1/manuscripts/image-texts/{text.id}/regions/"
    res = api_client.get(url)
    assert res.status_code == 200
    regions = {r["graph_id"]: r for r in res.data["regions"]}

    live = regions[text_graph.id]
    assert live["exists"] and live["is_text"] and live["same_image"]
    assert live["text"] == "Alpha"
    assert live["geometry"]["type"] == "Feature"

    dangling = regions[999999]
    assert dangling["exists"] is False
    assert dangling["geometry"] is None

    # Editorial regions are for signed-in users only.
    assert regions[editorial.id]["exists"] is False
    assert regions[editorial.id]["geometry"] is None
    signed_in = {r["graph_id"]: r for r in authenticated_client.get(url).data["regions"]}
    assert signed_in[editorial.id]["exists"] is True
    assert signed_in[editorial.id]["geometry"]["type"] == "Feature"


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
    assert not Graph.all_objects.filter(id=graph.id).exists()
    text.refresh_from_db()
    assert "corresp" not in text.content


@pytest.mark.django_db
def test_unlink_element_removes_one_link_keeps_graph_and_siblings(management_client, management_user):
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
    EditEvent.objects.all().delete()

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
    edit = EditEvent.objects.get(target_type="imagetext", target_id=text.id)
    assert edit.actor == management_user


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
def test_link_region_without_geometry_or_graph_id_is_400_with_a_detail_string(management_client):
    text = ImageText.objects.create(
        item_image=ItemImageFactory(),
        content="<p><seg>Rex</seg></p>",
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/link-region/",
        {"element_index": 0},
        format="json",
    )
    assert res.status_code == 400
    # A plain string, as the frontend shows the body verbatim; not DRF's list-wrapped field error.
    assert res.json() == {"detail": "geometry (GeoJSON) or graph_id is required."}


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
def test_graph_viewer_write_delete_trashes_and_preserves_corresp(authenticated_client):
    # The viewer delete is now a soft delete (trash): the row survives with
    # deleted_at set and the corresp reference is deliberately left in place,
    # so a restore brings the text↔region link back with no replay logic.
    # The corresp-strip signal fires only on a real delete (purge / cascade) —
    # covered in apps/annotations/tests/test_graph_trash.py.
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
    graph.refresh_from_db()
    assert graph.deleted_at is not None
    text.refresh_from_db()
    assert f"gid-{graph.id}" in text.content


@pytest.mark.django_db
def test_regions_reports_a_trashed_region_as_recoverable_to_staff_only(api_client, management_client):
    # Trashing keeps the corresp on purpose, so a trashed region must be
    # distinguishable from a purged one for the editor — but a delete must
    # still take the geometry off the public surface.
    image = ItemImageFactory()
    graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="text",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg corresp="#gid-{graph.id}">Alpha</seg><seg corresp="#gid-999999">gone</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
    )
    graph.soft_delete()

    url = f"/api/v1/manuscripts/image-texts/{text.id}/regions/"
    staff = {r["graph_id"]: r for r in management_client.get(url).data["regions"]}
    anon = {r["graph_id"]: r for r in api_client.get(url).data["regions"]}

    trashed = staff[graph.id]
    assert (trashed["exists"], trashed["is_text"], trashed["same_image"], trashed["trashed"]) == (
        True,
        True,
        True,
        True,
    )
    assert trashed["geometry"]["type"] == "Feature"
    assert staff[999999]["exists"] is False
    assert staff[999999]["trashed"] is False

    assert anon[graph.id]["exists"] is False
    assert anon[graph.id]["trashed"] is False
    assert anon[graph.id]["geometry"] is None


@pytest.mark.django_db
def test_link_region_restores_a_trashed_region(management_client):
    image = ItemImageFactory()
    graph = Graph.objects.create(item_image=image, annotation={"type": "Feature"}, annotation_type="text")
    text = ImageText.objects.create(
        item_image=image,
        content="<p><seg>Alpha</seg></p>",
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    graph.soft_delete()

    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/link-region/",
        {"element_index": 0, "graph_id": graph.id},
        format="json",
    )

    assert res.status_code == 200, res.data
    graph.refresh_from_db()
    assert graph.deleted_at is None
    assert f"gid-{graph.id}" in res.data["content"]

    # The restore rides in the same transaction as the ref it exists to serve.
    graph.soft_delete()
    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/link-region/",
        {"element_index": 99, "graph_id": graph.id},
        format="json",
    )
    assert res.status_code == 400
    graph.refresh_from_db()
    assert graph.deleted_at is not None


@pytest.mark.django_db
def test_check_text_links_counts_a_trashed_ref_instead_of_failing():
    from io import StringIO

    from django.core.management import call_command

    image = ItemImageFactory()
    graph = Graph.objects.create(item_image=image, annotation={"type": "Feature"}, annotation_type="text")
    ImageText.objects.create(
        item_image=image,
        content=f'<p><seg corresp="#gid-{graph.id}">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    graph.soft_delete()

    out = StringIO()
    call_command("check_text_links", stdout=out)

    assert "trashed: 1" in out.getvalue()
    assert "missing: 0" in out.getvalue()

    # The trashed bucket must not short-circuit the integrity checks: the same
    # ref pointing at another image is still a failure once trashed.
    graph.item_image = ItemImageFactory()
    graph.save(update_fields=["item_image"])
    with pytest.raises(SystemExit):
        call_command("check_text_links", stdout=StringIO(), stderr=StringIO())


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
