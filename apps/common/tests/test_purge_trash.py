"""`purge_trash` reaps the soft-delete trash without touching live rows.

Uses Graph as the concrete model because it is the only `SoftDeleteModel` today;
the command itself discovers models rather than naming them.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.common.models import EditEvent
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory


def _trash(graph: Graph, days_ago: int) -> None:
    graph.soft_delete()
    Graph.all_objects.filter(pk=graph.pk).update(deleted_at=timezone.now() - timedelta(days=days_ago))


def _run(*args: str) -> str:
    out = StringIO()
    call_command("purge_trash", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_dry_run_reports_without_deleting():
    graph = GraphFactory()
    _trash(graph, days_ago=100)

    output = _run("--older-than", "90")

    assert "annotations.Graph: 1" in output
    assert "would be purged" in output
    assert Graph.all_objects.filter(pk=graph.pk).exists()


@pytest.mark.django_db
def test_apply_purges_only_rows_past_the_cutoff():
    image = ItemImageFactory()
    old = GraphFactory(item_image=image)
    recent = GraphFactory(item_image=image, allograph=old.allograph, hand=old.hand)
    live = GraphFactory(item_image=image, allograph=old.allograph, hand=old.hand)
    _trash(old, days_ago=100)
    _trash(recent, days_ago=1)

    output = _run("--older-than", "90", "--apply")

    assert "Purged 1 row(s)" in output
    assert not Graph.all_objects.filter(pk=old.pk).exists()
    assert Graph.all_objects.filter(pk=recent.pk).exists()
    assert Graph.objects.filter(pk=live.pk).exists()


@pytest.mark.django_db
def test_older_than_zero_purges_the_whole_trash_but_spares_live_rows():
    image = ItemImageFactory()
    trashed = GraphFactory(item_image=image)
    live = GraphFactory(item_image=image, allograph=trashed.allograph, hand=trashed.hand)
    trashed.soft_delete()

    _run("--older-than", "0", "--apply")

    assert not Graph.all_objects.filter(pk=trashed.pk).exists()
    assert Graph.objects.filter(pk=live.pk).exists()


@pytest.mark.django_db
def test_purge_is_a_real_delete_so_the_corresp_strip_and_audit_still_fire():
    """The whole point of reaping via `.delete()`: a purged region must not leave
    a dangling `corresp` behind, and it must stay attributable in the log."""
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
    graph_id = graph.id
    _trash(graph, days_ago=100)

    _run("--older-than", "90", "--apply")

    text.refresh_from_db()
    assert f"gid-{graph_id}" not in text.content
    assert EditEvent.objects.filter(target_type="graph", target_id=graph_id, action=EditEvent.Action.DELETED).exists()


@pytest.mark.django_db
def test_empty_trash_reports_nothing_to_purge():
    GraphFactory()

    assert "Nothing to purge." in _run("--older-than", "0", "--apply")


@pytest.mark.django_db
def test_model_flag_scopes_the_purge_and_rejects_unknown_labels():
    graph = GraphFactory()
    _trash(graph, days_ago=100)

    assert "annotations.Graph: 1" in _run("--older-than", "90", "--model", "annotations.graph")

    with pytest.raises(CommandError, match="not a soft-deletable model"):
        _run("--older-than", "90", "--model", "manuscripts.ImageText")


@pytest.mark.django_db
def test_negative_retention_is_rejected():
    with pytest.raises(CommandError, match="0 or more"):
        _run("--older-than", "-1")
