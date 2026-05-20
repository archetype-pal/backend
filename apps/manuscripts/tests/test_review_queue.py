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


@pytest.mark.django_db
class TestStatusTransitionHistory:
    def test_history_returns_all_transitions_newest_first(self, management_client):
        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        # Drive two transitions through the audited endpoint so we exercise the
        # same code path the editor will trigger from the UI.
        management_client.post(
            f"/api/v1/manuscripts/management/image-texts/{text.pk}/transition/",
            data={"to_status": ImageText.Status.REVIEW, "note": "first"},
            format="json",
        )
        management_client.post(
            f"/api/v1/manuscripts/management/image-texts/{text.pk}/transition/",
            data={"to_status": ImageText.Status.LIVE, "note": "second"},
            format="json",
        )
        response = management_client.get(f"/api/v1/manuscripts/management/image-texts/{text.pk}/history/")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 2
        assert rows[0]["to_status"] == ImageText.Status.LIVE
        assert rows[0]["note"] == "second"
        assert rows[1]["to_status"] == ImageText.Status.REVIEW
        assert rows[1]["note"] == "first"
        assert rows[0]["actor_username"]  # management_client is authenticated

    def test_history_empty_for_text_with_no_transitions(self, management_client):
        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        response = management_client.get(f"/api/v1/manuscripts/management/image-texts/{text.pk}/history/")
        assert response.status_code == 200
        assert response.json() == []

    def test_history_requires_superuser(self, api_client):
        text = ImageTextFactory()
        response = api_client.get(f"/api/v1/manuscripts/management/image-texts/{text.pk}/history/")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestImageTextManagementFilters:
    def test_language_unset_sentinel_returns_blank_language_rows(self, management_client):
        ImageTextFactory(language="")
        ImageTextFactory(language="la")
        response = management_client.get("/api/v1/manuscripts/management/image-texts/?language=__unset__")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert all(r["language"] == "" for r in rows)
        assert len(rows) == 1

    def test_empty_true_returns_only_blank_content(self, management_client):
        ImageTextFactory(content="")
        ImageTextFactory(content="hello")
        response = management_client.get("/api/v1/manuscripts/management/image-texts/?empty=true")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert all(r["is_empty"] for r in rows)
        assert len(rows) == 1

    def test_list_includes_label_and_locus_for_ui(self, management_client):
        text = ImageTextFactory()
        response = management_client.get(f"/api/v1/manuscripts/management/image-texts/?item_image={text.item_image_id}")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert len(rows) == 1
        row = rows[0]
        # The list UI needs both the part id (for breadcrumbs/back-links) and a
        # human label, neither of which the bare FK id provides.
        assert row["item_part_id"] == text.item_image.item_part_id
        assert row["item_image_locus"] == text.item_image.locus
        assert row["item_image_label"]
