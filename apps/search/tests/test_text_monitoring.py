"""Tests for the image-text monitoring overview endpoint."""

import pytest
from rest_framework import status

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory

URL = "/api/v1/search/management/image-texts/overview/"


@pytest.fixture
def populated_corpus(db):
    img_a = ItemImageFactory()
    img_b = ItemImageFactory()
    img_c = ItemImageFactory()  # has neither

    ImageTextFactory(
        item_image=img_a,
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
        content="abc",
    )
    ImageTextFactory(
        item_image=img_a,
        type=ImageText.Type.TRANSLATION,
        status=ImageText.Status.LIVE,
        language="en",
        content="hello world",
    )
    ImageTextFactory(
        item_image=img_b,
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.REVIEW,
        language="",
        content="",
    )
    return {"a": img_a, "b": img_b, "c": img_c}


@pytest.mark.django_db
class TestTextMonitoringOverview:
    def test_anonymous_is_rejected(self, api_client):
        response = api_client.get(URL)
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_regular_user_is_rejected(self, authenticated_client):
        response = authenticated_client.get(URL)
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_superuser_gets_payload_shape(self, management_client, populated_corpus):
        response = management_client.get(URL)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert {
            "generated_at",
            "matrix",
            "coverage",
            "languages",
            "recent",
            "activity",
            "annotation_health",
        } <= set(body)

        matrix = body["matrix"]
        assert matrix["kinds"] == [
            ImageText.Type.TRANSCRIPTION,
            ImageText.Type.TRANSLATION,
        ]
        assert set(matrix["statuses"]) == {
            ImageText.Status.DRAFT,
            ImageText.Status.REVIEW,
            ImageText.Status.LIVE,
            ImageText.Status.REVIEWED,
        }
        # 2 transcriptions, 1 translation in our fixture.
        assert matrix["totals"][ImageText.Type.TRANSCRIPTION] == 2
        assert matrix["totals"][ImageText.Type.TRANSLATION] == 1
        assert matrix["by_kind"][ImageText.Type.TRANSCRIPTION][ImageText.Status.DRAFT] == 1
        assert matrix["by_kind"][ImageText.Type.TRANSCRIPTION][ImageText.Status.REVIEW] == 1
        assert matrix["by_kind"][ImageText.Type.TRANSLATION][ImageText.Status.LIVE] == 1
        # img_b's transcription is empty.
        assert matrix["empty_by_kind"][ImageText.Type.TRANSCRIPTION] == 1
        assert matrix["empty_by_kind"][ImageText.Type.TRANSLATION] == 0

    def test_coverage_counts(self, management_client, populated_corpus):
        response = management_client.get(URL)
        cov = response.json()["coverage"]
        assert cov["images_total"] >= 3
        assert cov["with_transcription"] >= 2
        assert cov["with_translation"] >= 1
        assert cov["with_both"] >= 1
        assert cov["with_either"] >= 2
        # img_c has no texts.
        assert cov["with_neither"] >= 1

    def test_languages_breakdown(self, management_client, populated_corpus):
        response = management_client.get(URL)
        langs = {row["language"]: row for row in response.json()["languages"]}
        assert "la" in langs
        assert langs["la"]["transcription"] == 1
        assert "en" in langs
        assert langs["en"]["translation"] == 1
        # Empty language strings should appear under "(unset)".
        assert "(unset)" in langs
        assert langs["(unset)"]["transcription"] >= 1

    def test_recent_activity_has_fields(self, management_client, populated_corpus):
        response = management_client.get(URL)
        recent = response.json()["recent"]
        assert recent, "expected at least one recent edit"
        for row in recent:
            assert {
                "id",
                "type",
                "status",
                "language",
                "modified",
                "created",
                "is_empty",
                "char_count",
                "annotation_count",
                "item_image_id",
                "item_part_id",
                "label",
                "locus",
            } <= set(row)

    def test_annotation_health(self, management_client, populated_corpus):
        response = management_client.get(URL)
        health = response.json()["annotation_health"]
        assert health["image_texts_total"] >= 3
        assert health["image_texts_with_content"] >= 2
        assert health["annotations_total"] >= 0
        assert health["average_annotations_per_text"] >= 0
