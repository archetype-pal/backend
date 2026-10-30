"""MsDescArea: model, management API, public gate and search-sync propagation."""

from __future__ import annotations

from unittest import mock

from django.db import IntegrityError, transaction
from django.test import override_settings
import pytest

from apps.manuscripts.models import MsDescArea
from apps.manuscripts.services.tei import msdesc
from apps.manuscripts.tests.factories import ItemPartFactory, MsDescAreaFactory


def test_area_names_match_model_choices():
    # msdesc.py is Django-free, so the model's TextChoices duplicate the
    # area names — this pins the two lists together.
    assert tuple(MsDescArea.Area.values) == msdesc.MSDESC_AREAS


@pytest.mark.django_db
class TestMsDescAreaModel:
    def test_one_row_per_area_per_part(self):
        area = MsDescAreaFactory()
        MsDescAreaFactory(area=area.area)  # the same area on another part is fine
        with pytest.raises(IntegrityError), transaction.atomic():
            MsDescAreaFactory(item_part=area.item_part, area=area.area)


@pytest.mark.django_db
class TestMsDescAreaManagementViewSet:
    def _url(self, pk=None):
        base = "/api/v1/manuscripts/management/msdesc-areas/"
        return f"{base}{pk}/" if pk else base

    def test_create(self, management_client):
        part = ItemPartFactory()
        response = management_client.post(
            self._url(),
            data={
                "item_part": part.pk,
                "area": MsDescArea.Area.HISTORY,
                "content": "<history><origin><origDate when='1200'>1200</origDate></origin></history>",
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        row = response.json()
        assert row["area"] == MsDescArea.Area.HISTORY
        assert row["is_published"] is False

    def test_create_rejects_unknown_area(self, management_client):
        part = ItemPartFactory()
        response = management_client.post(
            self._url(),
            data={"item_part": part.pk, "area": "additional", "content": "<additional/>"},
            format="json",
        )
        assert response.status_code == 400

    def test_filter_by_item_part_and_area(self, management_client):
        keep = MsDescAreaFactory(area=MsDescArea.Area.PHYS_DESC)
        MsDescAreaFactory(item_part=keep.item_part, area=MsDescArea.Area.HISTORY)
        MsDescAreaFactory(area=MsDescArea.Area.PHYS_DESC)  # other part
        response = management_client.get(f"{self._url()}?item_part={keep.item_part_id}&area=physDesc")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert [r["id"] for r in rows] == [keep.pk]

    def test_update_publishes_area(self, management_client):
        area = MsDescAreaFactory()
        response = management_client.patch(self._url(area.pk), data={"is_published": True}, format="json")
        assert response.status_code == 200
        area.refresh_from_db()
        assert area.is_published is True

    def test_delete(self, management_client):
        area = MsDescAreaFactory()
        response = management_client.delete(self._url(area.pk))
        assert response.status_code == 204
        assert not MsDescArea.objects.filter(pk=area.pk).exists()


@pytest.mark.django_db
class TestHistoricalItemDetailNesting:
    def test_detail_nests_msdesc_areas_per_part(self, management_client):
        area = MsDescAreaFactory(is_published=False)
        other_part_of_same_item = ItemPartFactory(historical_item=area.item_part.historical_item)
        response = management_client.get(
            f"/api/v1/manuscripts/management/historical-items/{area.item_part.historical_item_id}/"
        )
        assert response.status_code == 200
        parts = {p["id"]: p for p in response.json()["item_parts"]}
        # The management payload includes unpublished areas — the workspace
        # edits drafts; only the public serializer applies the gate.
        assert parts[area.item_part_id]["msdesc_areas"] == [
            {
                "id": area.pk,
                "item_part": area.item_part_id,
                "area": area.area,
                "content": area.content,
                "is_published": False,
            }
        ]
        assert parts[other_part_of_same_item.pk]["msdesc_areas"] == []


@pytest.mark.django_db
class TestPublicItemPartDetail:
    def _url(self, part):
        return f"/api/v1/manuscripts/item-parts/{part.pk}/"

    def test_shows_only_published_areas(self, api_client):
        published = MsDescAreaFactory(area=MsDescArea.Area.PHYS_DESC, is_published=True)
        MsDescAreaFactory(
            item_part=published.item_part,
            area=MsDescArea.Area.HISTORY,
            is_published=False,
        )
        response = api_client.get(self._url(published.item_part))
        assert response.status_code == 200
        # Only the published area, and only its public fields (no id /
        # is_published leak).
        assert response.json()["msdesc_areas"] == [{"area": "physDesc", "content": published.content}]

    def test_empty_when_nothing_published(self, api_client):
        area = MsDescAreaFactory(is_published=False)
        response = api_client.get(self._url(area.item_part))
        assert response.status_code == 200
        assert response.json()["msdesc_areas"] == []


@pytest.mark.django_db
class TestMsDescAreaReindexPropagation:
    """Every MsDescArea mutation syncs its item part's document on commit.

    The item part is created outside each capture block because creating one is
    itself a write.
    """

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_save_enqueues_item_part_sync(self, django_capture_on_commit_callbacks):
        part = ItemPartFactory()
        with (
            mock.patch("apps.search.signals.sync_search_documents") as task,
            django_capture_on_commit_callbacks(execute=True),
        ):
            MsDescAreaFactory(item_part=part)
        task.delay.assert_called_once_with("item-parts", [part.pk])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_delete_enqueues_item_part_sync(self, django_capture_on_commit_callbacks):
        area = MsDescAreaFactory()
        with (
            mock.patch("apps.search.signals.sync_search_documents") as task,
            django_capture_on_commit_callbacks(execute=True),
        ):
            area.delete()
        task.delay.assert_called_once_with("item-parts", [area.item_part_id])
