"""Phase G — reviewer queue + status transition tests."""

from __future__ import annotations

import pytest

from apps.manuscripts.models import ImageText, StatusTransition
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory


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


@pytest.mark.django_db
class TestImageTextBulkAction:
    def _url(self):
        return "/api/v1/manuscripts/management/image-texts/bulk_action/"

    def test_bulk_transition_writes_one_audit_row_per_text(self, management_client):
        texts = [ImageTextFactory(status=ImageText.Status.DRAFT) for _ in range(3)]
        response = management_client.post(
            self._url(),
            data={
                "ids": [t.pk for t in texts],
                "action": "transition",
                "payload": {"to_status": ImageText.Status.REVIEW, "note": "batch"},
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json() == {"affected": 3}
        for t in texts:
            t.refresh_from_db()
            assert t.status == ImageText.Status.REVIEW
            transitions = list(t.status_transitions.all())
            assert len(transitions) == 1
            assert transitions[0].note == "batch"

    def test_bulk_set_language_updates_in_one_query(self, management_client):
        a = ImageTextFactory(language="")
        b = ImageTextFactory(language="enm")
        response = management_client.post(
            self._url(),
            data={"ids": [a.pk, b.pk], "action": "set_language", "payload": {"language": "la"}},
            format="json",
        )
        assert response.status_code == 200
        assert response.json() == {"affected": 2}
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.language == "la"
        assert b.language == "la"

    def test_bulk_delete_removes_rows(self, management_client):
        texts = [ImageTextFactory() for _ in range(2)]
        other = ImageTextFactory()
        response = management_client.post(
            self._url(),
            data={"ids": [t.pk for t in texts], "action": "delete"},
            format="json",
        )
        assert response.status_code == 200
        assert response.json() == {"affected": 2}
        assert ImageText.objects.filter(pk__in=[t.pk for t in texts]).count() == 0
        # Sibling not in `ids` survives — the action is precisely scoped.
        assert ImageText.objects.filter(pk=other.pk).exists()

    def test_bulk_action_rejects_unknown_action(self, management_client):
        text = ImageTextFactory()
        response = management_client.post(
            self._url(),
            data={"ids": [text.pk], "action": "bogus"},
            format="json",
        )
        assert response.status_code == 400

    def test_bulk_action_rejects_non_int_ids(self, management_client):
        response = management_client.post(
            self._url(),
            data={"ids": ["one", "two"], "action": "delete"},
            format="json",
        )
        assert response.status_code == 400

    def test_bulk_action_requires_superuser(self, api_client):
        response = api_client.post(self._url(), data={"ids": [], "action": "delete"}, format="json")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestImageTextExport:
    def test_csv_export_includes_filtered_rows_only(self, management_client):
        keep = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, language="la")
        ImageTextFactory(type=ImageText.Type.TRANSLATION, language="la")  # filtered out
        response = management_client.get("/api/v1/manuscripts/management/image-texts/export/?type=Transcription")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert 'attachment; filename="image-texts.csv"' in response["Content-Disposition"]
        body = response.content.decode()
        lines = body.strip().splitlines()
        # Header + one matching row.
        assert len(lines) == 2
        assert "id" in lines[0]
        assert str(keep.pk) in lines[1]

    def test_csv_export_neutralises_formula_prefix(self, management_client):
        # An admin opening this CSV in Excel would otherwise see `language`
        # interpreted as a formula. The export must single-quote-prefix it.
        ImageTextFactory(language="=cmd|'/c calc'!A1")
        response = management_client.get("/api/v1/manuscripts/management/image-texts/export/")
        body = response.content.decode()
        # The dangerous cell is wrapped in CSV double-quotes (because it
        # contains a comma), so look for the prefix inside the quoted value.
        assert "\"'=cmd" in body or "'=cmd" in body

    def test_json_export_returns_metadata_payload(self, management_client):
        text = ImageTextFactory(content="hello world")
        response = management_client.get("/api/v1/manuscripts/management/image-texts/export/?format=json")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        payload = response.json()
        row = next(r for r in payload if r["id"] == text.pk)
        assert row["char_count"] == len("hello world")
        assert row["is_empty"] is False


@pytest.mark.django_db
class TestItemImageHasTextFilter:
    def test_has_text_false_returns_only_uncovered_images(self, management_client):
        covered = ImageTextFactory().item_image
        uncovered = ItemImageFactory()
        response = management_client.get("/api/v1/manuscripts/management/item-images/?has_text=false")
        assert response.status_code == 200
        ids = {r["id"] for r in response.json()["results"]}
        assert uncovered.pk in ids
        assert covered.pk not in ids

    def test_has_transcription_false_excludes_images_with_transcription(self, management_client):
        with_transcr = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION).item_image
        only_transl = ImageTextFactory(type=ImageText.Type.TRANSLATION).item_image
        response = management_client.get("/api/v1/manuscripts/management/item-images/?has_transcription=false")
        ids = {r["id"] for r in response.json()["results"]}
        assert with_transcr.pk not in ids
        assert only_transl.pk in ids
