"""Tests for the `sole_image_text` (read) and `upsert_sole_image_text` (write) endpoints."""

from __future__ import annotations

import pytest
from rest_framework import status

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory


@pytest.mark.django_db
class TestSoleImageTextRead:
    def test_anonymous_sees_live_text(self, api_client):
        image = ItemImageFactory()
        live = ImageTextFactory(item_image=image, type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE)
        response = api_client.get(f"/api/v1/manuscripts/item-images/{image.id}/transcription/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == live.id

    def test_anonymous_does_not_see_draft(self, api_client):
        image = ItemImageFactory()
        ImageTextFactory(item_image=image, type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.DRAFT)
        response = api_client.get(f"/api/v1/manuscripts/item-images/{image.id}/transcription/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_staff_sees_draft(self, management_client):
        image = ItemImageFactory()
        draft = ImageTextFactory(item_image=image, type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.DRAFT)
        response = management_client.get(f"/api/v1/manuscripts/item-images/{image.id}/transcription/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == draft.id

    def test_unknown_kind_is_400(self, api_client):
        image = ItemImageFactory()
        response = api_client.get(f"/api/v1/manuscripts/item-images/{image.id}/notathing/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestUpsertSoleImageText:
    def test_anonymous_is_forbidden(self, api_client):
        image = ItemImageFactory()
        response = api_client.put(
            f"/api/v1/manuscripts/management/item-images/{image.id}/transcription/",
            data={"content": "hello"},
            format="json",
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_creates_when_missing(self, management_client):
        image = ItemImageFactory()
        response = management_client.put(
            f"/api/v1/manuscripts/management/item-images/{image.id}/transcription/",
            data={"content": "hello", "language": "la"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        assert ImageText.objects.filter(item_image=image, type=ImageText.Type.TRANSCRIPTION).count() == 1
        row = ImageText.objects.get(item_image=image, type=ImageText.Type.TRANSCRIPTION)
        assert row.content == "hello"
        assert row.language == "la"
        assert row.status == ImageText.Status.DRAFT  # default

    def test_updates_when_present(self, management_client):
        image = ItemImageFactory()
        existing = ImageTextFactory(
            item_image=image,
            type=ImageText.Type.TRANSCRIPTION,
            content="old",
            status=ImageText.Status.LIVE,
        )
        response = management_client.put(
            f"/api/v1/manuscripts/management/item-images/{image.id}/transcription/",
            data={"content": "new", "status": ImageText.Status.LIVE},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        existing.refresh_from_db()
        assert existing.content == "new"
        # Still exactly one row — uniqueness preserved.
        assert ImageText.objects.filter(item_image=image, type=ImageText.Type.TRANSCRIPTION).count() == 1

    def test_unknown_image_is_404(self, management_client):
        response = management_client.put(
            "/api/v1/manuscripts/management/item-images/9999/transcription/",
            data={"content": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unknown_kind_is_400(self, management_client):
        image = ItemImageFactory()
        response = management_client.put(
            f"/api/v1/manuscripts/management/item-images/{image.id}/notathing/",
            data={"content": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
