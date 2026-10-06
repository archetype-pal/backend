"""Management (backoffice) list behaviour for Scribe."""

import pytest

from apps.scribes.tests.factories import ScribeFactory


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
