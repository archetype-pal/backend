"""The management ItemImage `image` field: path in, IIIF identifier out.

Regression tests for the backoffice 400 bug (DRF auto-mapped the IIIFField to
a binary ImageField), for the deliberate policy that raw file bytes must enter
through the chunked upload pipeline (JP2 normalization + image-server smoke
test) rather than this endpoint, and for the read/write asymmetry: the
identifier this endpoint returns must not be storable back as a path.
"""

import io

from PIL import Image
import pytest

from apps.manuscripts.models import ItemImage
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


def test_patch_rejects_the_identifier_it_returns(management_client):
    """The backoffice dialog prefilled its path input from this row's IIIF URL
    and sent it back on every save, including a locus-only edit. That PATCH
    400'd because of the very bug this PR fixes, which masked the problem; now
    that it succeeds, storing the URL would break the literal-path lookup."""
    image = ItemImageFactory(image="bl/old.jp2")

    response = management_client.patch(
        f"{BASE_URL}{image.pk}/",
        {"locus": "f.1r", "image": image.image.iiif.identifier},
        format="json",
    )

    assert response.status_code == 400
    image.refresh_from_db()
    assert image.image.name == "bl/old.jp2"


def test_multipart_file_upload_is_rejected(management_client):
    """Raw bytes on this endpoint would bypass JP2 normalization (issue #114
    recurrence vector), so files are rejected outright."""
    image = ItemImageFactory(image="bl/old.jp2")
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = "upload.png"

    response = management_client.patch(f"{BASE_URL}{image.pk}/", {"image": buffer}, format="multipart")

    assert response.status_code == 400
    assert "path" in str(response.data["image"][0]).lower()


def test_create_with_path_string(management_client):
    part = ItemPartFactory()
    response = management_client.post(
        BASE_URL,
        {"item_part": part.pk, "image": "bl/created.jp2", "locus": "f.3r"},
        format="json",
    )
    assert response.status_code == 201, response.data
    created = ItemImage.objects.get(pk=response.data["id"])
    assert created.image.name == "bl/created.jp2"
    assert response.data["image"] == created.image.iiif.identifier


def test_representation_is_the_iiif_identifier(management_client):
    """This field's only consumers render a thumbnail from it, and a bare
    storage path resolves nowhere on a deployment whose IIIF_HOST carries a
    path prefix — so the identifier is what goes out."""
    image = ItemImageFactory(image="bl/repr.jp2")

    response = management_client.get(f"{BASE_URL}{image.pk}/")

    assert response.status_code == 200
    assert response.data["image"] == image.image.iiif.identifier
    assert response.data["image"] != "bl/repr.jp2"
    assert "bl%2Frepr.jp2" in response.data["image"]
