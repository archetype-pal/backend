"""End-to-end contract of the DigiPal → Archetype text migration (docs/tei-backup-migration.md).

A tiny legacy corpus — `data-dpt` HTML transcriptions, region graphs that know
their element only through `annotation.properties.elementid` — goes through
the same commands, in the same order, as `scripts/migrate_backup_to_tei.sh`
runs them. This is the behaviour an adopter with a DigiPal database relies on.
"""

from importlib import import_module
from io import StringIO

from django.apps import apps
from django.core.management import call_command
import pytest

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import parse_graph_refs, validate_tei_wellformed
from apps.manuscripts.tests.factories import ItemImageFactory

_MIGRATION = "apps.manuscripts.migrations.0027_embed_text_region_links"
embed_text_region_links = import_module(_MIGRATION).embed_text_region_links

POLYGON = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]}}

LEGACY_TRANSCRIPTION = (
    "<p>"
    '<span data-dpt="clause" data-dpt-cat="words" data-dpt-type="address">Omnibus hominibus</span> '
    '<span data-dpt="person" data-dpt-cat="chars" data-dpt-type="name">Willelmus</span> rex&nbsp;Anglorum'
    "</p>"
)
LEGACY_TRANSLATION = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="address">To all men</span> William king</p>'
)


def _run(command: str, *args: str) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out, stderr=out)
    return out.getvalue()


@pytest.mark.django_db
def test_legacy_corpus_migrates_to_linked_tei():
    image = ItemImageFactory()
    transcription = ImageText.objects.create(
        item_image=image, content=LEGACY_TRANSCRIPTION, type=ImageText.Type.TRANSCRIPTION, status="Live"
    )
    translation = ImageText.objects.create(
        item_image=image, content=LEGACY_TRANSLATION, type=ImageText.Type.TRANSLATION, status="Live"
    )
    # The DigiPal export links a region to its clause on the graph side only.
    region = Graph.objects.create(
        item_image=image,
        annotation_type="text",
        annotation={**POLYGON, "properties": {"elementid": [["", "clause"], ["type", "address"]]}},
    )

    # 1. `migrate` embeds the graph-side links into the texts (migration 0027; both texts of the pair match).
    embed_text_region_links(apps, None)
    for text in (transcription, translation):
        text.refresh_from_db()
        assert f'data-graph-id="{region.id}"' in text.content

    # 2. Convert data-dpt HTML to TEI; the link becomes `corresp`, entities become characters.
    summary = _run("migrate_imagetext_to_tei", "--apply")
    assert "failed: 0" in summary
    transcription.refresh_from_db()
    assert '<seg type="address" corresp="#gid-' in transcription.content
    assert "<persName" in transcription.content
    assert "&nbsp;" not in transcription.content and "\xa0" in transcription.content
    assert validate_tei_wellformed(transcription.content) == []

    # Re-running is a no-op: already-TEI rows are recognised and skipped.
    assert "already_tei: 2" in _run("migrate_imagetext_to_tei", "--apply")

    # 3. Re-encode the graph's elementid as the reverse link the IIIF/W3C layers read.
    _run("reencode_graph_elementid", "--apply")
    region.refresh_from_db()
    refs = region.annotation["properties"]["elementid"]["refs"]
    assert {ref["image_text"] for ref in refs} == {transcription.id, translation.id}
    assert region.annotation["properties"]["legacy_dpt_elementid"] == [["", "clause"], ["type", "address"]]

    # 4. Both gates pass: every link resolves, every text is well-formed TEI.
    assert "missing: 0" in _run("check_text_links")
    assert "invalid: 0" in _run("verify_tei")

    # What the application reads afterwards: one region ref per text, pointing at the graph.
    assert [ref.graph_ids for ref in parse_graph_refs(transcription.content)] == [[region.id]]


@pytest.mark.django_db
def test_rows_that_do_not_round_trip_are_left_as_data_dpt_and_fail_the_gate():
    image = ItemImageFactory()
    # An unclosed span cannot be converted losslessly, so it must stay untouched for manual review.
    broken = ImageText.objects.create(
        item_image=image, content='<p><span data-dpt="clause">Alpha</p>', type="Transcription", status="Live"
    )

    summary = _run("migrate_imagetext_to_tei", "--apply")
    assert "failed: 1" in summary and str(broken.id) in summary
    broken.refresh_from_db()
    assert broken.content == '<p><span data-dpt="clause">Alpha</p>'

    with pytest.raises(SystemExit):
        _run("verify_tei")
