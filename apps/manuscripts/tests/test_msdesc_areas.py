"""TEI-descriptions Phases 0.2/1.1/1.2/1.4 — MsDescArea model, vocab, API, reindex."""

from __future__ import annotations

from unittest import mock

from django.db import IntegrityError, transaction
import pytest

from apps.manuscripts.models import MsDescArea
from apps.manuscripts.services.tei import msdesc
from apps.manuscripts.tests.factories import ItemPartFactory, MsDescAreaFactory


class TestMsDescVocab:
    """The 0.2 vocab module — transcription sanity, not ODD re-derivation."""

    def test_all_vocabularies_non_empty(self):
        assert msdesc.MSDESC_AREAS
        for key, values in msdesc.MSDESC_VOCABULARIES.items():
            assert values, f"empty vocabulary for {key}"

    def test_aggregate_dict_covers_every_named_tuple(self):
        assert set(msdesc.MSDESC_VOCABULARIES) == {
            "objectDesc@form",
            "supportDesc@material",
            "handNote@script",
            "handNote@execution",
            "decoNote@type",
            "availability@status",
            "layout@topLine",
            "layout@rulingMedium",
        }

    def test_spot_check_odd_values(self):
        # One canonical value per list, straight from the ODD's valItems.
        assert "codex" in msdesc.OBJECT_DESC_FORMS
        assert "perg" in msdesc.SUPPORT_DESC_MATERIALS
        assert "textualisNorthern" in msdesc.HAND_NOTE_SCRIPTS
        assert "formata" in msdesc.HAND_NOTE_EXECUTIONS
        assert "flourInit" in msdesc.DECO_NOTE_TYPES
        assert "restricted" in msdesc.AVAILABILITY_STATUSES
        assert "below" in msdesc.LAYOUT_TOP_LINES
        assert "leadpoint" in msdesc.LAYOUT_RULING_MEDIA

    def test_area_names_match_model_choices(self):
        # msdesc.py is Django-free, so the model's TextChoices duplicate the
        # area names — this pins the two lists together.
        assert tuple(MsDescArea.Area.values) == msdesc.MSDESC_AREAS


@pytest.mark.django_db
class TestMsDescAreaModel:
    def test_one_row_per_area_per_part(self):
        area = MsDescAreaFactory()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                MsDescAreaFactory(item_part=area.item_part, area=area.area)

    def test_same_area_allowed_on_different_parts(self):
        a = MsDescAreaFactory(area=MsDescArea.Area.HISTORY)
        b = MsDescAreaFactory(area=MsDescArea.Area.HISTORY)
        assert a.item_part_id != b.item_part_id

    def test_defaults_to_unpublished(self):
        assert MsDescAreaFactory().is_published is False


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

    def test_anonymous_denied(self, api_client):
        response = api_client.get(self._url())
        assert response.status_code in (401, 403)

    def test_regular_user_denied(self, authenticated_client):
        part = ItemPartFactory()
        assert authenticated_client.get(self._url()).status_code == 403
        response = authenticated_client.post(
            self._url(),
            data={"item_part": part.pk, "area": MsDescArea.Area.HISTORY, "content": "<history/>"},
            format="json",
        )
        assert response.status_code == 403


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
    """7.1 — every MsDescArea mutation enqueues an item-parts reindex on commit."""

    def test_save_enqueues_item_parts_reindex(self, django_capture_on_commit_callbacks):
        with mock.patch("apps.search.signals.reindex_search_index") as task:
            with django_capture_on_commit_callbacks(execute=True):
                MsDescAreaFactory()
        task.delay.assert_called_once_with("item-parts")

    def test_update_enqueues_item_parts_reindex(self, django_capture_on_commit_callbacks):
        area = MsDescAreaFactory()
        with mock.patch("apps.search.signals.reindex_search_index") as task:
            with django_capture_on_commit_callbacks(execute=True):
                area.is_published = True
                area.save(update_fields=["is_published", "modified"])
        task.delay.assert_called_once_with("item-parts")

    def test_delete_enqueues_item_parts_reindex(self, django_capture_on_commit_callbacks):
        area = MsDescAreaFactory()
        with mock.patch("apps.search.signals.reindex_search_index") as task:
            with django_capture_on_commit_callbacks(execute=True):
                area.delete()
        task.delay.assert_called_once_with("item-parts")

    def test_viewset_write_enqueues_via_on_commit(self, management_client, django_capture_on_commit_callbacks):
        part = ItemPartFactory()
        with mock.patch("apps.search.signals.reindex_search_index") as task:
            with django_capture_on_commit_callbacks(execute=True):
                response = management_client.post(
                    "/api/v1/manuscripts/management/msdesc-areas/",
                    data={"item_part": part.pk, "area": MsDescArea.Area.MS_CONTENTS, "content": "<msContents/>"},
                    format="json",
                )
        assert response.status_code == 201
        task.delay.assert_called_once_with("item-parts")
