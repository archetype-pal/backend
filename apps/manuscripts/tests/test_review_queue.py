"""Phase G — reviewer queue + status transition tests."""

from __future__ import annotations

import pytest

from apps.manuscripts.models import ImageText, StatusTransition
from apps.manuscripts.tests.factories import ImageTextFactory


@pytest.mark.django_db
class TestReviewQueue:
    def test_queue_only_shows_review_status(self, management_client):
        ImageTextFactory(status=ImageText.Status.DRAFT)
        ImageTextFactory(status=ImageText.Status.REVIEW)
        ImageTextFactory(status=ImageText.Status.LIVE)
        response = management_client.get("/api/v1/manuscripts/management/review-queue/")
        assert response.status_code == 200
        statuses = {row["status"] for row in response.json()}
        assert statuses == {ImageText.Status.REVIEW}

    def test_queue_orders_oldest_first(self, management_client):
        # Two reviews — older one should sort first.
        old = ImageTextFactory(status=ImageText.Status.REVIEW)
        new = ImageTextFactory(status=ImageText.Status.REVIEW)
        # Force `modified` ordering deterministically.
        ImageText.objects.filter(pk=old.pk).update(modified="2026-01-01T00:00:00Z")
        ImageText.objects.filter(pk=new.pk).update(modified="2026-04-01T00:00:00Z")
        response = management_client.get("/api/v1/manuscripts/management/review-queue/")
        ids = [row["id"] for row in response.json()]
        assert ids[0] == old.pk
        assert ids[-1] == new.pk

    def test_anonymous_cannot_see_queue(self, api_client):
        response = api_client.get("/api/v1/manuscripts/management/review-queue/")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestStatusTransition:
    def test_transition_records_audit_row(self, management_client):
        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        response = management_client.post(
            f"/api/v1/manuscripts/management/image-texts/{text.pk}/transition/",
            data={"to_status": ImageText.Status.REVIEW, "note": "ready"},
            format="json",
        )
        assert response.status_code == 200, response.json()
        text.refresh_from_db()
        assert text.status == ImageText.Status.REVIEW
        rows = StatusTransition.objects.filter(image_text=text).all()
        assert rows.count() == 1
        assert rows[0].from_status == ImageText.Status.DRAFT
        assert rows[0].to_status == ImageText.Status.REVIEW
        assert rows[0].note == "ready"

    def test_transition_to_review_can_assign(self, management_client, django_user_model):
        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        reviewer = django_user_model.objects.create_user(username="reviewer", is_staff=True)
        response = management_client.post(
            f"/api/v1/manuscripts/management/image-texts/{text.pk}/transition/",
            data={"to_status": ImageText.Status.REVIEW, "assignee": reviewer.pk},
            format="json",
        )
        assert response.status_code == 200
        text.refresh_from_db()
        assert text.review_assignee_id == reviewer.pk

    def test_transition_clears_assignee_when_leaving_review(self, management_client, django_user_model):
        reviewer = django_user_model.objects.create_user(username="reviewer", is_staff=True)
        text = ImageTextFactory(status=ImageText.Status.REVIEW, review_assignee=reviewer)
        response = management_client.post(
            f"/api/v1/manuscripts/management/image-texts/{text.pk}/transition/",
            data={"to_status": ImageText.Status.LIVE},
            format="json",
        )
        assert response.status_code == 200
        text.refresh_from_db()
        assert text.review_assignee_id is None

    def test_transition_rejects_unknown_status(self, management_client):
        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        response = management_client.post(
            f"/api/v1/manuscripts/management/image-texts/{text.pk}/transition/",
            data={"to_status": "Bogus"},
            format="json",
        )
        assert response.status_code == 400
