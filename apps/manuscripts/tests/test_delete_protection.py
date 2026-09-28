"""Deleting a repository or current item that is still in use answers 409 (#228).

`CurrentItem.repository` used to CASCADE and `ItemPart.current_item` SET_NULL, so
deleting a repository silently took its current items with it and left their
parts pointing at nothing.
"""

import pytest
import rest_framework

from apps.manuscripts.models import CurrentItem, ItemPart, Repository
from apps.manuscripts.tests.factories import CurrentItemFactory, ItemPartFactory, RepositoryFactory

REPOSITORIES_URL = "/api/v1/manuscripts/management/repositories/"
CURRENT_ITEMS_URL = "/api/v1/manuscripts/management/current-items/"


@pytest.mark.django_db
def test_repository_with_current_items_cannot_be_deleted(management_client):
    part = ItemPartFactory()
    repository = part.current_item.repository

    response = management_client.delete(f"{REPOSITORIES_URL}{repository.id}/")

    assert response.status_code == rest_framework.status.HTTP_409_CONFLICT, response.data
    assert response.data["detail"] == "Cannot delete: still referenced by 1 current item."
    assert Repository.objects.filter(id=repository.id).exists()
    part.refresh_from_db()
    assert part.current_item_id is not None


@pytest.mark.django_db
def test_current_item_with_parts_cannot_be_deleted(management_client):
    part = ItemPartFactory()

    response = management_client.delete(f"{CURRENT_ITEMS_URL}{part.current_item_id}/")

    assert response.status_code == rest_framework.status.HTTP_409_CONFLICT, response.data
    assert response.data["detail"] == "Cannot delete: still referenced by 1 item part."
    assert ItemPart.objects.get(id=part.id).current_item_id is not None


@pytest.mark.django_db
def test_unused_repository_and_current_item_still_delete(management_client):
    current_item = CurrentItemFactory()
    repository = RepositoryFactory()

    assert management_client.delete(f"{CURRENT_ITEMS_URL}{current_item.id}/").status_code == 204
    assert management_client.delete(f"{REPOSITORIES_URL}{repository.id}/").status_code == 204
    assert not CurrentItem.objects.filter(id=current_item.id).exists()
    assert not Repository.objects.filter(id=repository.id).exists()


@pytest.mark.django_db
def test_repository_list_reports_current_item_count(management_client):
    current_item = CurrentItemFactory()
    CurrentItemFactory(repository=current_item.repository)
    RepositoryFactory()

    response = management_client.get(REPOSITORIES_URL, {"limit": 100})

    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    counts = {row["id"]: row["current_item_count"] for row in rows}
    assert counts[current_item.repository_id] == 2
    assert sorted(counts.values()) == [0, 2]
