"""Graph trash (soft delete): every delete path trashes instead of destroying,
trashed rows leak into no read surface, and restore/purge behave as documented.

Trash is a save() — the pre_delete corresp-strip signal must NOT fire (so a
restored TEXT graph keeps its text link); purge is a real delete and must fire it.
"""

import pytest
import rest_framework

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.annotations.tests.test_write_guards import WRITE_ENDPOINTS
from apps.common.models import EditEvent
from apps.manuscripts.models import ItemImage
from apps.manuscripts.tests.factories import ItemImageFactory, image_text, text_region
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
    assert image.graphs.count() == 0


@pytest.mark.django_db
def test_the_deleted_param_switches_between_the_live_list_and_the_trash(management_client):
    live = GraphFactory()
    trashed = GraphFactory(item_image=live.item_image, allograph=live.allograph, hand=live.hand)
    trashed.soft_delete()

    for value in ("true", "1", "True", "TRUE", "yes", "on"):
        rows = management_client.get(f"{MANAGEMENT_URL}?deleted={value}").data["results"]
        assert {row["id"] for row in rows} == {trashed.id}, value
        assert rows[0]["deleted_at"] is not None
    # Absent, blank and `null` are what a cleared filter / URLSearchParams
    # round-trip emits — they mean "live", not "garbage".
    for value in (None, "false", "0", "", "null"):
        params = {} if value is None else {"deleted": value}
        rows = management_client.get(MANAGEMENT_URL, params).data["results"]
        assert {row["id"] for row in rows} == {live.id}, value
    assert management_client.get(f"{MANAGEMENT_URL}?deleted=nonsense").status_code == 400

    # A row the trash list handed out is addressable by detail.
    detail = management_client.get(f"{MANAGEMENT_URL}{trashed.id}/")
    assert detail.status_code == 200
    assert detail.data["deleted_at"] is not None


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
    EditEvent.objects.filter(target_type="graph", target_id=graph_id).delete()

    res = management_client.delete(f"{MANAGEMENT_URL}{graph_id}/purge/")
    assert res.status_code == rest_framework.status.HTTP_204_NO_CONTENT
    assert not Graph.all_objects.filter(id=graph_id).exists()
    # Purge is a real delete, so it logs `deleted` and not one of the trash verbs.
    events = EditEvent.objects.filter(target_type="graph", target_id=graph_id)
    assert {e.action for e in events} == {EditEvent.Action.DELETED}
    assert all(e.actor is not None for e in events)


@pytest.mark.django_db
def test_non_superuser_cannot_trash_editorial(authenticated_client):
    editorial = GraphFactory(allograph=None, hand=None, annotation_type=Graph.AnnotationType.EDITORIAL)

    assert authenticated_client.delete(f"{VIEWER_URL}{editorial.id}/").status_code == 404
    editorial.refresh_from_db()
    assert editorial.deleted_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(("client_fixture", "url"), WRITE_ENDPOINTS)
def test_trash_preserves_corresp_and_purge_strips_it(request, management_client, client_fixture, url):
    client = request.getfixturevalue(client_fixture)
    image = ItemImageFactory()
    graph = text_region(image)
    text = image_text(image, f'<p><seg type="address" corresp="#gid-{graph.id}">Alpha</seg></p>')

    # Trash: a save(), so the pre_delete corresp-strip must NOT run.
    res = client.delete(f"{url}{graph.id}/")
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
def test_unlink_region_on_trashed_graph_hard_deletes(management_client):
    """F7 regression test: unlinking a region graph that is already trashed must
    hard-delete it from all_objects so it doesn't survive in trash as an orphan."""
    image = ItemImageFactory()
    graph = text_region(image)
    text = image_text(image, f'<p><seg corresp="#gid-{graph.id}">Alpha</seg></p>')

    graph.soft_delete()
    assert graph.deleted_at is not None

    res = management_client.post(
        f"/api/v1/manuscripts/management/image-texts/{text.id}/unlink-region/",
        {"graph_id": graph.id},
        format="json",
    )

    assert res.status_code == 200
    assert f"gid-{graph.id}" not in res.data["content"]
    assert not Graph.all_objects.filter(id=graph.id).exists()
    # The purge is attributable, like every other delete path.
    assert EditEvent.objects.filter(target_type="graph", target_id=graph.id).latest("id").actor is not None


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
def test_cascade_delete_collects_trashed_children():
    """_base_manager invariant: deleting a parent model (ItemImage) must collect
    and delete its trashed children without raising IntegrityError."""
    graph = GraphFactory()
    image_id = graph.item_image_id
    graph.soft_delete()
    assert graph.deleted_at is not None

    ItemImage.objects.get(pk=image_id).delete()
    assert not Graph.all_objects.filter(pk=graph.pk).exists()


@pytest.mark.django_db
def test_trash_and_restore_log_their_own_verbs():
    """A2: trash/restore are save()s, so they used to log as a generic `updated`.

    The verb is derived from the write's `update_fields` signature, so nothing
    has to be flagged by the caller — and a save that touches anything else
    still logs `updated`.
    """
    graph = GraphFactory()
    EditEvent.objects.all().delete()

    graph.soft_delete()
    graph.restore()
    graph.note = "an ordinary edit"
    graph.save()

    actions = list(
        EditEvent.objects.filter(target_type="graph", target_id=graph.id)
        .order_by("created", "id")
        .values_list("action", flat=True)
    )
    assert actions == [
        EditEvent.Action.TRASHED,
        EditEvent.Action.RESTORED,
        EditEvent.Action.UPDATED,
    ]


@pytest.mark.django_db
def test_restore_event_payload_preserves_trash_provenance():
    """A3: restore() clears deleted_at/deleted_by, so the append-only EditEvent
    payload is the only durable record of who trashed the row and when.

    Asserts the exact keys, because `payload` is an unvalidated JSONField in an
    append-only table — a misspelled key cannot be fixed by a later code change,
    and a consumer querying the right spelling would silently match nothing.
    """
    from apps.users.tests.factories import UserFactory

    alice = UserFactory(username="alice")
    graph = GraphFactory()
    graph.soft_delete(user=alice)
    trashed_at = graph.deleted_at
    EditEvent.objects.all().delete()

    graph.restore()

    event = EditEvent.objects.get(target_type="graph", target_id=graph.id)
    assert event.action == EditEvent.Action.RESTORED
    assert event.payload == {
        "previously_deleted_by": "alice",
        "previously_deleted_at": trashed_at.isoformat(),
    }
    # The shape a future consumer would actually query on.
    assert EditEvent.objects.filter(payload__previously_deleted_by="alice").count() == 1


@pytest.mark.django_db
def test_restore_event_payload_when_no_deleter_recorded():
    """`soft_delete()` without a user leaves deleted_by NULL — the key stays
    present and null rather than vanishing, so the payload shape is stable."""
    graph = GraphFactory()
    graph.soft_delete()
    EditEvent.objects.all().delete()

    graph.restore()

    event = EditEvent.objects.get(target_type="graph", target_id=graph.id)
    assert event.payload["previously_deleted_by"] is None
    assert event.payload["previously_deleted_at"] is not None
