"""The management ItemImage `image` field accepts ONLY path strings.

Regression tests for the backoffice 400 bug (DRF auto-mapped the IIIFField to
a binary ImageField) and guards for the deliberate policy that raw file bytes
must enter through /api/v1/uploads/ (JP2 normalization + SIPI smoke test),
never through this endpoint.
"""

import io

from PIL import Image
import pytest

from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory

pytestmark = pytest.mark.django_db

BASE_URL = "/api/v1/manuscripts/management/item-images/"


def test_patch_with_path_string_succeeds(management_client):
    image = ItemImageFactory(image="bl/old.jp2")
    response = management_client.patch(
        f"{BASE_URL}{image.pk}/",
        {"locus": "f.1r", "image": "bl/new.jp2"},
        format="json",
    )
    assert response.status_code == 200, response.data
    image.refresh_from_db()
    assert image.image.name == "bl/new.jp2"
    assert image.locus == "f.1r"


def test_patch_without_image_field_succeeds(management_client):
    image = ItemImageFactory(image="bl/old.jp2")
    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"locus": "f.2v"}, format="json")
    assert response.status_code == 200, response.data
    image.refresh_from_db()
    assert image.image.name == "bl/old.jp2"


def test_patch_rejects_null_and_traversal(management_client):
    image = ItemImageFactory(image="bl/old.jp2")
    assert management_client.patch(f"{BASE_URL}{image.pk}/", {"image": None}, format="json").status_code == 400
    assert management_client.patch(f"{BASE_URL}{image.pk}/", {"image": "a/../b.jp2"}, format="json").status_code == 400


def test_multipart_file_upload_is_rejected_with_pointer_to_uploads(management_client):
    """Raw bytes on this endpoint would bypass JP2 normalization (issue #114
    recurrence vector), so files are rejected outright."""
    image = ItemImageFactory(image="bl/old.jp2")
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = "upload.png"

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"image": buffer}, format="multipart")

    assert response.status_code == 400
    assert "uploads" in str(response.data["image"][0])


def test_create_with_path_string(management_client):
    part = ItemPartFactory()
    response = management_client.post(
        BASE_URL,
        {"item_part": part.pk, "image": "bl/created.jp2", "locus": "f.3r"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["image"] == "bl/created.jp2"


def test_representation_is_relative_path(management_client):
    image = ItemImageFactory(image="bl/repr.jp2")
    response = management_client.get(f"{BASE_URL}{image.pk}/")
    assert response.status_code == 200
    assert response.data["image"] == "bl/repr.jp2"
