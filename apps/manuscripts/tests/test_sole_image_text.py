"""Tests for the `sole_image_text` (read) and `upsert_sole_image_text` (write) endpoints."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.exceptions import NotFound

from apps.common.models import EditEvent
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.image_texts import upsert_sole_text
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


@pytest.mark.django_db
class TestUpsertSoleTextService:
    def test_creates_the_row_under_the_actors_audit_scope(self, management_user):
        image = ItemImageFactory()

        row = upsert_sole_text(
            item_image_id=image.id,
            type_value=ImageText.Type.TRANSCRIPTION,
            defaults={"content": "hello", "language": "la"},
            actor=management_user,
        )

        assert row.content == "hello"
        assert ImageText.objects.filter(item_image=image, type=ImageText.Type.TRANSCRIPTION).count() == 1
        event = EditEvent.objects.filter(target_type="imagetext", target_id=row.pk).latest("created")
        assert event.actor == management_user

    def test_updates_the_existing_row(self, management_user):
        existing = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="old")

        row = upsert_sole_text(
            item_image_id=existing.item_image_id,
            type_value=ImageText.Type.TRANSCRIPTION,
            defaults={"content": "new"},
            actor=management_user,
        )

        assert row.pk == existing.pk
        assert row.content == "new"

    def test_unknown_image_is_not_found(self, management_user):
        with pytest.raises(NotFound):
            upsert_sole_text(
                item_image_id=9999, type_value=ImageText.Type.TRANSCRIPTION, defaults={}, actor=management_user
            )
