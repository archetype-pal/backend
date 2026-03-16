import csv

from django.core.management import call_command
import pytest

from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.management.commands.embed_annotation_ids import (
    ElementSpec,
    embed_annotation_ids_in_content,
    parse_elementid,
)
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory


def test_parse_elementid_extracts_expected_fields():
    spec = parse_elementid('[["", "clause"], ["type", "salutation"], ["@text", "salutem"]]')
    assert spec == ElementSpec(tag="clause", type_name="salutation", text_hint="salutem")


def test_embed_annotation_ids_in_content_merges_and_annotates_all_matches():
    content = (
        '<p><span data-dpt="clause" data-dpt-type="address">Alpha</span>'
        '<span data-dpt="clause" data-dpt-type="address" data-annotation-id="10">Beta</span></p>'
    )
    spec = ElementSpec(tag="clause", type_name="address", text_hint=None)

    new_content, matched_spans, changed_spans = embed_annotation_ids_in_content(content, spec, annotation_id=11)

    assert matched_spans == 2
    assert changed_spans == 2
    assert 'data-annotation-id="11"' in new_content
    assert 'data-annotation-id="10,11"' in new_content


def test_embed_annotation_ids_in_content_respects_text_hint():
    content = '<p><span data-dpt="person" data-dpt-type="name">David</span></p>'
    spec = ElementSpec(tag="person", type_name="name", text_hint="William")

    new_content, matched_spans, changed_spans = embed_annotation_ids_in_content(content, spec, annotation_id=99)

    assert matched_spans == 0
    assert changed_spans == 0
    assert new_content == content


@pytest.mark.django_db
def test_command_dry_run_does_not_persist_changes(tmp_path):
    item_image = ItemImageFactory()
    graph = GraphFactory(item_image=item_image)
    image_text = ImageText.objects.create(
        item_image=item_image,
        content='<p><span data-dpt="clause" data-dpt-type="address">To all</span></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    csv_path = tmp_path / "annotations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["id", "annotation_id", "elementid"])
        writer.writeheader()
        writer.writerow(
            {
                "id": 1,
                "annotation_id": graph.id,
                "elementid": '[["", "clause"], ["type", "address"]]',
            }
        )

    call_command("embed_annotation_ids", "--csv", str(csv_path), "--dry-run")

    image_text.refresh_from_db()
    assert 'data-annotation-id="' not in image_text.content


@pytest.mark.django_db
def test_command_apply_updates_transcription_and_translation(tmp_path):
    item_image = ItemImageFactory()
    graph = GraphFactory(item_image=item_image)
    transcription = ImageText.objects.create(
        item_image=item_image,
        content='<p><span data-dpt="clause" data-dpt-type="address">To all</span></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    translation = ImageText.objects.create(
        item_image=item_image,
        content='<p><span data-dpt="clause" data-dpt-type="address">To all</span></p>',
        type=ImageText.Type.TRANSLATION,
        status=ImageText.Status.DRAFT,
        language="en",
    )

    csv_path = tmp_path / "annotations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["id", "annotation_id", "elementid"])
        writer.writeheader()
        writer.writerow(
            {
                "id": 1,
                "annotation_id": graph.id,
                "elementid": '[["", "clause"], ["type", "address"]]',
            }
        )

    call_command("embed_annotation_ids", "--csv", str(csv_path), "--apply")

    transcription.refresh_from_db()
    translation.refresh_from_db()
    assert f'data-annotation-id="{graph.id}"' in transcription.content
    assert f'data-annotation-id="{graph.id}"' in translation.content
