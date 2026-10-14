"""Management (backoffice) list behaviour for Scribe."""

import pytest

from apps.scribes.tests.factories import HandFactory, ScribeFactory


@pytest.mark.django_db
class TestScribeManagementViewSet:
    url = "/api/v1/management/scribes/scribes/"

    def test_list_searches_name_and_scriptorium(self, management_client):
        ScribeFactory(name="UniqueScribeX", scriptorium="Glasgow")
        ScribeFactory(name="UniqueScribeY", scriptorium="Edinburgh")

        by_name = management_client.get(self.url, {"search": "UniqueScribeX"})
        assert [row["name"] for row in by_name.json()["results"]] == ["UniqueScribeX"]

        by_scriptorium = management_client.get(self.url, {"search": "Edinburgh"})
        assert [row["name"] for row in by_scriptorium.json()["results"]] == ["UniqueScribeY"]

    def test_list_filters_by_period(self, management_client):
        match = ScribeFactory()
        ScribeFactory()

        response = management_client.get(self.url, {"period": match.period_id})

        assert [row["id"] for row in response.json()["results"]] == [match.id]

    def test_ordering_by_hand_count(self, management_client):
        quiet = ScribeFactory(name="OrderingScribe")
        busy = ScribeFactory(name="OrderingScribe")
        HandFactory.create_batch(2, scribe=busy)

        by_hands = management_client.get(self.url, {"ordering": "-hand_count"})
        assert [(row["id"], row["hand_count"]) for row in by_hands.json()["results"]] == [(busy.id, 2), (quiet.id, 0)]

    def test_create_returns_zero_hand_count(self, management_client):
        response = management_client.post(self.url, {"name": "Fresh scribe"}, format="json")
        assert response.status_code == 201
        assert response.json()["hand_count"] == 0
