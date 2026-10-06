"""Management (backoffice) list behaviour for Scribe."""

import pytest

from apps.scribes.tests.factories import ScribeFactory


@pytest.mark.django_db
class TestScribeManagementViewSet:
    url = "/api/v1/management/scribes/scribes/"

    def test_list_supports_limit_and_search(self, management_client):
        ScribeFactory(name="UniqueScribeX", scriptorium="Glasgow")
        ScribeFactory(name="UniqueScribeY", scriptorium="Edinburgh")

        limited = management_client.get(self.url, {"limit": 1})
        assert limited.status_code == 200
        assert len(limited.json()["results"]) == 1
        assert limited.json()["count"] >= 2

        by_name = management_client.get(self.url, {"search": "UniqueScribeX"})
        assert [row["name"] for row in by_name.json()["results"]] == ["UniqueScribeX"]

        by_scriptorium = management_client.get(self.url, {"search": "Edinburgh"})
        assert [row["name"] for row in by_scriptorium.json()["results"]] == ["UniqueScribeY"]
