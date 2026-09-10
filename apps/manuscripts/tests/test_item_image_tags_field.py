"""The management ItemImage `tags` field accepts/returns a list of tag names.

Regression tests for the backoffice 400 bug (DRF auto-mapped the Tagulous
TagField to a to-many PrimaryKeyRelatedField expecting tag ids, but the
backoffice sends/expects free-text tag names).
"""

import pytest

from apps.manuscripts.models import ItemImage
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db

BASE_URL = "/api/v1/manuscripts/management/item-images/"


def test_patch_locus_only_leaves_tags_untouched(management_client):
    image = ItemImageFactory()
    image.tags = "alpha, beta"
    image.save()

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"locus": "f.5r"}, format="json")

    assert response.status_code == 200, response.data
    # Re-fetch rather than refresh_from_db(): the latter drops Tagulous' tag-
    # string cache without repopulating it, so a subsequent read can appear blank.
    refreshed = ItemImage.objects.get(pk=image.pk)
    assert refreshed.locus == "f.5r"
    assert sorted(t.name for t in refreshed.tags.all()) == ["alpha", "beta"]


def test_patch_tags_as_list_round_trips_lowercased(management_client):
    image = ItemImageFactory()

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"tags": ["Damaged", "Illuminated"]}, format="json")

    assert response.status_code == 200, response.data
    assert sorted(response.data["tags"]) == ["damaged", "illuminated"]
    refreshed = ItemImage.objects.get(pk=image.pk)
    assert sorted(t.name for t in refreshed.tags.all()) == ["damaged", "illuminated"]


def test_patch_tags_as_string_is_rejected_clearly(management_client):
    image = ItemImageFactory()

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"tags": "damaged"}, format="json")

    assert response.status_code == 400
    assert "tags" in response.data
    assert "list" in str(response.data["tags"][0]).lower()


def test_patch_tags_deduplicates_case_insensitively(management_client):
    """A duplicate tag name must not double-increment the shared Tag row's
    usage count for what is really a single relation."""
    image = ItemImageFactory()
    tag_model = ItemImage._meta.get_field("tags").tag_model

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"tags": ["Damaged", "damaged"]}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["tags"] == ["damaged"]
    refreshed = ItemImage.objects.get(pk=image.pk)
    assert [t.name for t in refreshed.tags.all()] == ["damaged"]
    assert tag_model.objects.get(name="damaged").count == 1


def test_patch_rejects_an_over_long_tag_name(management_client):
    """The tag model's `name` column is varchar(255) and Tagulous's manager
    writes it via get_or_create without validating, so an unbounded serializer
    field turns a bad request into a 500 on Postgres. SQLite ignores the
    declared length, so the field's own max_length is what catches this."""
    image = ItemImageFactory()

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"tags": ["x" * 256]}, format="json")

    assert response.status_code == 400
    assert "tags" in response.data
    refreshed = ItemImage.objects.get(pk=image.pk)
    assert list(refreshed.tags.all()) == []


def test_patch_tags_empty_list_clears_existing_tags(management_client):
    image = ItemImageFactory()
    image.tags = "alpha, beta"
    image.save()

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"tags": []}, format="json")

    assert response.status_code == 200, response.data
    refreshed = ItemImage.objects.get(pk=image.pk)
    assert list(refreshed.tags.all()) == []
