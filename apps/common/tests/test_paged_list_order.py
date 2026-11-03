"""Paging a list one row at a time visits every row once, in the list's order.

Each case creates rows whose sort key ties and is out of insertion order, so the
pages only line up when the list applies its order and breaks ties by id.
"""

from datetime import timedelta

from django.apps import apps
from django.db.models import Count
from django.utils import timezone
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.common.pagination import with_pk_tiebreak
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import (
    CurrentItemFactory,
    ImageTextFactory,
    ItemImageFactory,
    ItemPartFactory,
    RepositoryFactory,
)
from apps.publications.models import Event, Publication
from apps.publications.tests.factories import EventFactory, PublicationFactory
from apps.scribes.tests.factories import ScribeFactory

# Each row's rank in the list's order, in creation order: ties, and not sorted.
# Each maker below creates one row per rank and returns (sort key, id) pairs;
# the key is the rank, plus the id for a list that breaks ties newest first.
# More than six rows: Postgres sorts fewer with a stable insertion sort, which
# keeps ties in id order by chance.
RANKS = [2, 0, 1, 0, 2, 1, 0, 2, 1]


def _repositories(ranks):
    return [(rank, RepositoryFactory(name=f"Repository {rank}").pk) for rank in ranks]


def _current_items(ranks):
    repository = RepositoryFactory()
    return [(rank, CurrentItemFactory(repository=repository, shelfmark=f"MS {rank}").pk) for rank in ranks]


def _item_images(ranks):
    item_part = ItemPartFactory()
    return [(rank, ItemImageFactory(item_part=item_part, locus=f"f. {rank}").pk) for rank in ranks]


def _scribes(ranks):
    rows = [(rank, ScribeFactory(name=f"Scribe {rank}")) for rank in ranks]
    # Editing a row moves it in Postgres's storage, so tied names stop coming
    # back in id order by chance.
    for _, scribe in reversed(rows):
        scribe.save()
    return [(rank, scribe.pk) for rank, scribe in rows]


def _publications(ranks):
    now = timezone.now()
    rows = []
    for rank in ranks:
        publication = PublicationFactory()
        Publication.objects.filter(pk=publication.pk).update(created_at=now - timedelta(days=rank))
        rows.append((rank, publication.pk))
    return rows


def _events(ranks):
    # Newest first, and no view spells out a tiebreak: the paginator adds it.
    now = timezone.now()
    rows = []
    for rank in ranks:
        event = EventFactory()
        Event.objects.filter(pk=event.pk).update(created_at=now - timedelta(days=rank))
        rows.append((rank, event.pk))
    return rows


def _image_texts(ranks):
    # Newest first; texts created before migration 0010 all share one `created`.
    now = timezone.now()
    rows = []
    for rank in ranks:
        text = ImageTextFactory(status=ImageText.Status.LIVE)
        ImageText.objects.filter(pk=text.pk).update(created=now - timedelta(days=rank))
        rows.append(((rank, -text.pk), text.pk))
    return rows


def _trashed_graphs(ranks):
    now = timezone.now()
    rows = []
    for rank in ranks:
        graph = GraphFactory()
        Graph.all_objects.filter(pk=graph.pk).update(deleted_at=now - timedelta(minutes=rank))
        rows.append((rank, graph.pk))
    return rows


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "params", "make_rows"),
    [
        ("manuscripts/management/repositories", {}, _repositories),
        ("manuscripts/management/current-items", {}, _current_items),
        ("manuscripts/management/item-images", {}, _item_images),
        ("manuscripts/management/image-texts", {}, _image_texts),
        ("management/annotations/graphs", {"deleted": "true"}, _trashed_graphs),
        ("management/scribes/scribes", {}, _scribes),
        ("media/management/publications", {}, _publications),
        ("media/management/events", {}, _events),
    ],
)
def test_paging_one_row_at_a_time_lists_each_row_once_in_order(management_client, path, params, make_rows):
    rows = make_rows(RANKS)

    assert _ids_paged_one_row_at_a_time(management_client, path, params, len(rows)) == [pk for _, pk in sorted(rows)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "make_rows"),
    [
        ("manuscripts/item-images", _item_images),
        ("manuscripts/image-texts", _image_texts),
        ("scribes", _scribes),
        ("media/events", _events),
    ],
)
def test_paging_a_public_list_one_row_at_a_time_lists_each_row_once_in_order(api_client, path, make_rows):
    rows = make_rows(RANKS)

    assert _ids_paged_one_row_at_a_time(api_client, path, {}, len(rows)) == [pk for _, pk in sorted(rows)]


@pytest.mark.django_db
def test_the_tiebreak_leaves_a_grouped_values_query_alone():
    ImageTextFactory(type=ImageText.Type.TRANSCRIPTION)
    ImageTextFactory(type=ImageText.Type.TRANSCRIPTION)
    grouped = ImageText.objects.values("type").annotate(n=Count("id"))

    assert list(with_pk_tiebreak(grouped)) == [{"type": ImageText.Type.TRANSCRIPTION, "n": 2}]


def test_no_model_orders_across_a_relation():
    """The paginator restores a model's Meta.ordering under a GROUP BY; across a relation that would add a join."""
    crossing = [
        f"{model._meta.label}: {term}"
        for model in apps.get_models()
        if model.__module__.startswith("apps.")
        for term in model._meta.ordering
        if "__" in str(term)
    ]

    assert crossing == []


def _ids_paged_one_row_at_a_time(client, path, params, count):
    seen = []
    for offset in range(count):
        page = client.get(f"/api/v1/{path}/", {**params, "limit": 1, "offset": offset})
        assert page.status_code == 200, page.content
        seen += [row["id"] for row in page.data["results"]]
    return seen
