"""The image-text monitoring overview: exact figures over a small corpus."""

import pytest

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory

URL = "/api/v1/manuscripts/management/image-texts/overview/"
TRANSCRIPTION, TRANSLATION = ImageText.Type.TRANSCRIPTION, ImageText.Type.TRANSLATION

pytestmark = pytest.mark.django_db


def test_overview_aggregates_the_corpus(management_client):
    both = ItemImageFactory()
    transcription_only = ItemImageFactory()
    ItemImageFactory()  # neither
    ImageTextFactory(item_image=both, type=TRANSCRIPTION, status=ImageText.Status.DRAFT, language="la", content="abc")
    ImageTextFactory(item_image=both, type=TRANSLATION, status=ImageText.Status.LIVE, language="en", content="hello")
    ImageTextFactory(item_image=transcription_only, type=TRANSCRIPTION, status="Review", language="", content="")

    body = management_client.get(URL).json()

    matrix = body["matrix"]
    assert matrix["totals"] == {TRANSCRIPTION: 2, TRANSLATION: 1}
    assert matrix["by_kind"][TRANSCRIPTION] == {"Draft": 1, "Review": 1, "Live": 0, "Reviewed": 0}
    assert matrix["by_kind"][TRANSLATION] == {"Draft": 0, "Review": 0, "Live": 1, "Reviewed": 0}
    assert matrix["empty_by_kind"] == {TRANSCRIPTION: 1, TRANSLATION: 0}
    assert body["coverage"] == {
        "images_total": 3,
        "with_transcription": 2,
        "with_translation": 1,
        "with_both": 1,
        "with_either": 2,
        "with_neither": 1,
    }
    languages = {row["language"]: (row["transcription"], row["translation"]) for row in body["languages"]}
    assert languages == {"la": (1, 0), "en": (0, 1), "(unset)": (1, 0)}
    assert body["languages"][-1]["language"] == "(unset)"
    assert body["annotation_health"] == {
        "image_texts_total": 3,
        "image_texts_with_content": 2,
        "annotations_total": 0,
        "average_annotations_per_text": 0.0,
    }
    recent = {row["id"]: row for row in body["recent"]}
    assert len(recent) == 3
    assert recent[ImageText.objects.get(content="hello").id]["char_count"] == 5


def test_trashed_graph_drops_out_of_the_recent_annotation_count(management_client):
    """`recent[].annotation_count` is a joined Count, which the live-only default
    manager cannot reach — it must not disagree with annotation_health."""
    image = ItemImageFactory()
    text = ImageTextFactory(item_image=image, type=TRANSCRIPTION, content="abc")
    graph = Graph.objects.create(item_image=image, annotation={"type": "Feature"}, annotation_type="text")

    body = management_client.get(URL).json()
    assert next(row for row in body["recent"] if row["id"] == text.id)["annotation_count"] == 1
    assert body["annotation_health"]["annotations_total"] == 1

    graph.soft_delete()

    body = management_client.get(URL).json()
    assert next(row for row in body["recent"] if row["id"] == text.id)["annotation_count"] == 0
    assert body["annotation_health"]["annotations_total"] == 0
