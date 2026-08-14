"""Graph trash (soft delete): every delete path trashes instead of destroying,
trashed rows leak into no read surface, and restore/purge behave as documented.

Trash is a save() — the pre_delete corresp-strip signal must NOT fire (so a
restored TEXT graph keeps its text link); purge is a real delete and must fire
it. See content_trash_feature_plan.md.
"""

import pytest
import rest_framework

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.common.models import EditEvent
from apps.manuscripts.models import ImageText, ItemImage
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.scribes.services import get_scribe_idiographs
from apps.search.documents.item_images import build_item_image_document
from apps.search.registry import get_queryset_for_index
from apps.search.types import IndexType

VIEWER_URL = "/api/v1/annotations/graphs/"
PUBLIC_URL = "/api/v1/manuscripts/graphs/"
MANAGEMENT_URL = "/api/v1/management/annotations/graphs/"


@pytest.mark.django_db
def test_viewer_delete_moves_to_trash(authenticated_client):
    graph = GraphFactory()

    res = authenticated_client.delete(f"{VIEWER_URL}{graph.id}/")

    assert res.status_code == rest_framework.status.HTTP_204_NO_CONTENT
    graph.refresh_from_db()
    assert graph.deleted_at is not None
    assert graph.deleted_by is not None
    # A trashed row is invisible to the viewer write surface too.
    assert authenticated_client.delete(f"{VIEWER_URL}{graph.id}/").status_code == 404
    assert authenticated_client.patch(f"{VIEWER_URL}{graph.id}/", {"note": "x"}, format="json").status_code == 404


@pytest.mark.django_db
def test_management_delete_moves_to_trash(management_client):
    graph = GraphFactory()

    res = management_client.delete(f"{MANAGEMENT_URL}{graph.id}/")

    assert res.status_code == rest_framework.status.HTTP_204_NO_CONTENT
    graph.refresh_from_db()
    assert graph.deleted_at is not None


@pytest.mark.django_db
def test_trashed_graph_hidden_from_read_surfaces(management_client):
    graph = GraphFactory()
    image = graph.item_image
    graph.soft_delete()

    # Public list + detail (superuser client = widest visibility).
    listed = management_client.get(f"{PUBLIC_URL}?item_image={image.id}")
    assert all(row["id"] != graph.id for row in listed.data)
    assert management_client.get(f"{PUBLIC_URL}{graph.id}/").status_code == 404
    # W3C annotation endpoint.
    assert management_client.get(f"/api/v1/annotations-w3c/graphs/{graph.id}/").status_code == 404
    # Aggregate counts on the owning image.
    assert image.number_of_annotations() == 0


@pytest.mark.django_db
def test_management_list_deleted_param(management_client):
    live = GraphFactory()
    trashed = GraphFactory(item_image=live.item_image, allograph=live.allograph, hand=live.hand)
    trashed.soft_delete()

    default_rows = management_client.get(MANAGEMENT_URL).data["results"]
    assert {row["id"] for row in default_rows} == {live.id}

    trash_rows = management_client.get(f"{MANAGEMENT_URL}?deleted=true").data["results"]
    assert {row["id"] for row in trash_rows} == {trashed.id}
    assert trash_rows[0]["deleted_at"] is not None


@pytest.mark.django_db
def test_trash_list_filters(management_client):
    """The trash surface filters by annotation type, who trashed it, and when."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.users.tests.factories import UserFactory

    alice = UserFactory(username="alice")
    bob = UserFactory(username="bob")
    image = ItemImageFactory()

    old = GraphFactory(item_image=image)
    old.soft_delete(user=alice)
    Graph.all_objects.filter(pk=old.pk).update(deleted_at=timezone.now() - timedelta(days=10))

    recent = GraphFactory(item_image=image, allograph=old.allograph, hand=old.hand)
    recent.soft_delete(user=bob)

    editorial = GraphFactory(
        item_image=image, allograph=None, hand=None, annotation_type=Graph.AnnotationType.EDITORIAL
    )
    editorial.soft_delete(user=bob)

    def ids(query: str) -> set[int]:
        res = management_client.get(f"{MANAGEMENT_URL}?deleted=true&{query}")
        assert res.status_code == rest_framework.status.HTTP_200_OK, res.data
        return {row["id"] for row in res.data["results"]}

    assert ids("") == {old.id, recent.id, editorial.id}
    assert ids("annotation_type=editorial") == {editorial.id}
    assert ids("deleted_by__username=alice") == {old.id}
    assert ids("deleted_by__username=bob") == {recent.id, editorial.id}

    # "Z" rather than "+00:00": a raw "+" in a query string decodes to a space,
    # which the date parser rejects. This is the shape the frontend sends
    # (Date.toISOString()), so the test exercises the real contract.
    cutoff = (timezone.now() - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    assert ids(f"deleted_at__gte={cutoff}") == {recent.id, editorial.id}
    assert ids(f"deleted_at__lte={cutoff}") == {old.id}
    # Filters compose.
    assert ids(f"deleted_at__gte={cutoff}&deleted_by__username=bob&annotation_type=editorial") == {editorial.id}


@pytest.mark.django_db
def test_trash_actors_lists_only_users_with_trashed_rows(management_client, authenticated_client):
    from apps.users.tests.factories import UserFactory

    alice = UserFactory(username="alice")
    UserFactory(username="never_deleted_anything")
    image = ItemImageFactory()

    # Two rows from alice: she must appear exactly once, not twice. Meta.ordering
    # would silently break the DISTINCT if the view didn't override it.
    first = GraphFactory(item_image=image)
    first.soft_delete(user=alice)
    GraphFactory(item_image=image, allograph=first.allograph, hand=first.hand).soft_delete(user=alice)

    # A live row's owner is not a trash actor.
    GraphFactory(item_image=image, allograph=first.allograph, hand=first.hand)
    # Neither is a trashed row with no recorded deleter.
    GraphFactory(item_image=image, allograph=first.allograph, hand=first.hand).soft_delete()

    res = management_client.get(f"{MANAGEMENT_URL}trash-actors/")

    assert res.status_code == rest_framework.status.HTTP_200_OK
    assert res.data == ["alice"]

    # Superuser-only, like the rest of the management surface.
    assert authenticated_client.get(f"{MANAGEMENT_URL}trash-actors/").status_code == 403


@pytest.mark.django_db
def test_live_list_filters_still_work(management_client):
    """Switching filterset_fields to dict form must not rename existing params."""
    image = ItemImageFactory()
    live = GraphFactory(item_image=image, annotation_type=Graph.AnnotationType.IMAGE)
    # GraphFactory leaves annotation_type NULL by default, so this row must not
    # match an `annotation_type=image` filter.
    GraphFactory(item_image=image, allograph=live.allograph, hand=live.hand)

    res = management_client.get(f"{MANAGEMENT_URL}?annotation_type=image&item_image={image.id}")

    assert res.status_code == rest_framework.status.HTTP_200_OK
    assert {row["id"] for row in res.data["results"]} == {live.id}


@pytest.mark.django_db
def test_restore(management_client, authenticated_client):
    graph = GraphFactory()
    graph.soft_delete()

    # Restore is superuser-only.
    assert authenticated_client.post(f"{MANAGEMENT_URL}{graph.id}/restore/").status_code == 403

    res = management_client.post(f"{MANAGEMENT_URL}{graph.id}/restore/")
    assert res.status_code == rest_framework.status.HTTP_200_OK
    graph.refresh_from_db()
    assert graph.deleted_at is None
    assert graph.deleted_by is None
    # Restoring a live row 404s (restore targets the trash only).
    assert management_client.post(f"{MANAGEMENT_URL}{graph.id}/restore/").status_code == 404


@pytest.mark.django_db
def test_purge(management_client, authenticated_client):
    graph = GraphFactory()
    graph_id = graph.id

    # Purge targets trashed rows only, and is superuser-only.
    assert management_client.delete(f"{MANAGEMENT_URL}{graph_id}/purge/").status_code == 404
    graph.soft_delete()
    assert authenticated_client.delete(f"{MANAGEMENT_URL}{graph_id}/purge/").status_code == 403

    res = management_client.delete(f"{MANAGEMENT_URL}{graph_id}/purge/")
    assert res.status_code == rest_framework.status.HTTP_204_NO_CONTENT
    assert not Graph.all_objects.filter(id=graph_id).exists()
    event = EditEvent.objects.filter(target_type="graph", target_id=graph_id, action=EditEvent.Action.DELETED).first()
    assert event is not None
    assert event.actor is not None


@pytest.mark.django_db
def test_non_superuser_cannot_trash_editorial(authenticated_client):
    editorial = GraphFactory(allograph=None, hand=None, annotation_type=Graph.AnnotationType.EDITORIAL)

    assert authenticated_client.delete(f"{VIEWER_URL}{editorial.id}/").status_code == 404
    editorial.refresh_from_db()
    assert editorial.deleted_at is None


@pytest.mark.django_db
def test_trash_preserves_corresp_and_purge_strips_it(management_client):
    image = ItemImageFactory()
    graph = Graph.objects.create(
        item_image=image,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
        annotation_type="text",
    )
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg type="address" corresp="#gid-{graph.id}">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    # Trash: a save(), so the pre_delete corresp-strip must NOT run.
    res = management_client.delete(f"{MANAGEMENT_URL}{graph.id}/")
    assert res.status_code == rest_framework.status.HTTP_204_NO_CONTENT
    text.refresh_from_db()
    assert f"gid-{graph.id}" in text.content

    # Restore: the link is intact with no replay logic.
    management_client.post(f"{MANAGEMENT_URL}{graph.id}/restore/")
    text.refresh_from_db()
    assert f"gid-{graph.id}" in text.content

    # Purge: a real delete — the signal strips the reference.
    graph.refresh_from_db()
    graph.soft_delete()
    res = management_client.delete(f"{MANAGEMENT_URL}{graph.id}/purge/")
    assert res.status_code == rest_framework.status.HTTP_204_NO_CONTENT
    assert not Graph.all_objects.filter(id=graph.id).exists()
    text.refresh_from_db()
    assert f"gid-{graph.id}" not in text.content


@pytest.mark.django_db
def test_unlink_region_still_hard_deletes(management_client):
    """Deliberate decision: unlink-region keeps its hard delete (it strips the
    ref first, so a restored region would be an unreachable orphan)."""
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

    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-region/",
        {"graph_id": graph.id},
        format="json",
    )

    assert res.status_code == 200
    assert not Graph.all_objects.filter(id=graph.id).exists()


@pytest.mark.django_db
def test_unlink_region_on_trashed_graph_hard_deletes(management_client):
    """F7 regression test: unlinking a region graph that is already trashed must
    hard-delete it from all_objects so it doesn't survive in trash as an orphan."""
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

    graph.soft_delete()
    assert graph.deleted_at is not None

    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-region/",
        {"graph_id": graph.id},
        format="json",
    )

    assert res.status_code == 200
    text.refresh_from_db()
    assert f"gid-{graph.id}" not in text.content
    assert not Graph.all_objects.filter(id=graph.id).exists()


@pytest.mark.django_db
def test_search_queryset_and_image_document_exclude_trashed():
    graph = GraphFactory()
    image = graph.item_image

    assert graph.id in set(get_queryset_for_index(IndexType.GRAPHS).values_list("id", flat=True))
    assert build_item_image_document(image)["number_of_annotations"] == 1

    graph.soft_delete()

    assert graph.id not in set(get_queryset_for_index(IndexType.GRAPHS).values_list("id", flat=True))
    assert build_item_image_document(image)["number_of_annotations"] == 0


@pytest.mark.django_db
def test_scribe_idiographs_exclude_trashed():
    graph = GraphFactory()
    scribe = graph.hand.scribe

    assert [a.id for a in get_scribe_idiographs(scribe)] == [graph.allograph_id]

    graph.soft_delete()

    assert get_scribe_idiographs(scribe) == []


@pytest.mark.django_db
def test_components_of_trashed_graph_hidden(management_client):
    from apps.annotations.tests.factories import GraphComponentFactory

    gc = GraphComponentFactory()
    url = "/api/v1/management/annotations/graph-components/"

    res = management_client.get(f"{url}?graph={gc.graph_id}")
    assert {row["id"] for row in res.data["results"]} == {gc.id}

    gc.graph.soft_delete()

    res = management_client.get(url)
    assert res.status_code == rest_framework.status.HTTP_200_OK, res.data
    assert gc.id not in {row["id"] for row in res.data["results"]}

    # django-filter validates `graph` against Graph.objects, which no longer
    # sees the trashed row, so the id is rejected rather than matching nothing.
    res = management_client.get(f"{url}?graph={gc.graph_id}")
    assert res.status_code == rest_framework.status.HTTP_400_BAD_REQUEST, res.data


@pytest.mark.django_db
def test_schema_graph_management_component(management_client):
    # Authenticated on purpose. /api/v1/schema/ merges the YAMLs verbatim, so the
    # document is identical either way — but an anonymous client spends the shared
    # anon throttle budget (100/h) that the pre-existing 429-flaky tests in
    # test_auth_api / TestWorksetCitableReads run right up against.
    res = management_client.get("/api/v1/schema/")
    assert res.status_code == 200
    schema = res.json()
    schemas = schema["components"]["schemas"]

    assert "Graph" in schemas
    assert "GraphManagement" in schemas

    # Public Graph schema must not carry management/trash fields
    public_props = schemas["Graph"]["properties"]
    assert "created" not in public_props
    assert "deleted_at" not in public_props
    assert "deleted_by" not in public_props

    # Management schema must reference Graph and declare trash fields
    mgmt_all_of = schemas["GraphManagement"]["allOf"]
    assert mgmt_all_of[0]["$ref"] == "#/components/schemas/Graph"
    mgmt_props = mgmt_all_of[1]["properties"]
    assert "created" in mgmt_props
    assert "deleted_at" in mgmt_props
    assert "deleted_by" in mgmt_props


@pytest.mark.django_db
def test_cascade_delete_collects_trashed_children():
    """_base_manager invariant: deleting a parent model (ItemImage) must collect
    and delete its trashed children without raising IntegrityError."""
    graph = GraphFactory()
    image_id = graph.item_image_id
    graph.soft_delete()
    assert graph.deleted_at is not None

    ItemImage.objects.get(pk=image_id).delete()
    assert not Graph.all_objects.filter(pk=graph.pk).exists()
