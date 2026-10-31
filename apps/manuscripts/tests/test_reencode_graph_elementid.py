"""The Graph.elementid re-encoding command."""

from django.core.management import call_command
import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory, image_text, text_region

pytestmark = pytest.mark.django_db


def _setup():
    image = ItemImageFactory()
    graph = text_region(
        image, annotation={"type": "Feature", "geometry": {}, "properties": {"elementid": [["", "person"]]}}
    )
    text = image_text(
        image, f'<p><persName type="name" corresp="#gid-{graph.id}">Walter</persName></p>', status=ImageText.Status.LIVE
    )
    return image, graph, text


def test_dry_run_writes_nothing():
    _, graph, _ = _setup()
    call_command("reencode_graph_elementid")
    graph.refresh_from_db()
    assert graph.annotation["properties"]["elementid"] == [["", "person"]]
    assert "legacy_dpt_elementid" not in graph.annotation["properties"]


def test_apply_reencodes_and_preserves_legacy():
    _, graph, text = _setup()
    call_command("reencode_graph_elementid", "--apply")
    graph.refresh_from_db()
    props = graph.annotation["properties"]
    assert props["legacy_dpt_elementid"] == [["", "person"]]
    refs = props["elementid"]["refs"]
    assert len(refs) == 1
    # HTMLParser lowercases tag names, as throughout the TEI parsing layer.
    assert refs[0] == {
        "image_text": text.id,
        "kind": "Transcription",
        "element": "persname",
        "type": "name",
        "text": "Walter",
    }


def test_reverse_restores_legacy():
    _, graph, _ = _setup()
    call_command("reencode_graph_elementid", "--apply")
    call_command("reencode_graph_elementid", "--reverse")
    graph.refresh_from_db()
    props = graph.annotation["properties"]
    assert props["elementid"] == [["", "person"]]
    assert "legacy_dpt_elementid" not in props


def test_reverse_removes_synthetic_when_no_original_elementid():
    # A referenced TEXT graph with NO original elementid gains a synthetic one
    # on --apply; --reverse must REMOVE it (not leave residue).
    image = ItemImageFactory()
    graph = text_region(image, annotation={"type": "Feature", "geometry": {}, "properties": {}})
    image_text(image, f'<p><seg type="address" corresp="#gid-{graph.id}">x</seg></p>', status=ImageText.Status.LIVE)
    call_command("reencode_graph_elementid", "--apply")
    graph.refresh_from_db()
    assert "elementid" in graph.annotation["properties"]  # synthetic added
    call_command("reencode_graph_elementid", "--reverse")
    graph.refresh_from_db()
    props = graph.annotation["properties"]
    assert "elementid" not in props  # synthetic removed, not left as residue
    assert "legacy_dpt_elementid" not in props


def test_unreferenced_graph_untouched():
    image = ItemImageFactory()
    graph = text_region(
        image, annotation={"type": "Feature", "geometry": {}, "properties": {"elementid": [["", "clause"]]}}
    )
    call_command("reencode_graph_elementid", "--apply")
    graph.refresh_from_db()
    # No ImageText references it → left as-is.
    assert graph.annotation["properties"]["elementid"] == [["", "clause"]]
