import pytest
from rest_framework import status

URL = "/api/v1/search/management/actions/"


@pytest.fixture
def queued(monkeypatch):
    calls = []

    class _Result:
        id = "task-1"

    def record(*args):
        calls.append(args)
        return _Result()

    monkeypatch.setattr("apps.search.tasks.reindex_search_index.delay", record)
    monkeypatch.setattr("apps.search.tasks.clear_search_index.delay", record)
    monkeypatch.setattr("apps.search.tasks.reindex_all_search_indexes.delay", record)
    return calls


@pytest.mark.django_db
def test_a_per_index_action_queues_the_task_for_that_index(management_client, queued):
    res = management_client.post(URL, {"action": "reindex", "index_type": "item-parts"}, format="json")

    assert res.status_code == status.HTTP_200_OK
    assert res.data["task_id"] == "task-1"
    assert queued == [("item-parts",)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"action": "defragment"}, "action"),
        ({"action": "reindex"}, "index_type"),
        ({"action": "reindex", "index_type": "unicorns"}, "index_type"),
    ],
)
def test_an_unknown_action_or_index_is_refused_before_anything_is_queued(management_client, queued, body, field):
    res = management_client.post(URL, body, format="json")

    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert field in res.data
    assert queued == []


@pytest.mark.django_db
def test_only_superusers_can_start_actions(authenticated_client, queued):
    res = authenticated_client.post(URL, {"action": "reindex_all"}, format="json")

    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert queued == []
