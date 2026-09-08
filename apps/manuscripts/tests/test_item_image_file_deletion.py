"""Deleting an ItemImage must remove its files from disk, not just the DB row.

Django's FileField leaves files behind on delete; a post_delete signal
(apps.manuscripts.signals) removes the served JP2. Deletion is deferred to
transaction.on_commit, so these tests execute the commit hooks via
`django_capture_on_commit_callbacks`.
"""

from pathlib import Path

import pytest

from apps.manuscripts.models import ItemImage
from apps.manuscripts.tests.factories import ItemPartFactory

pytestmark = pytest.mark.django_db


def _make_image(*, image_rel: str, item_part=None) -> ItemImage:
    """Create an ItemImage with a real served file on disk at `image_rel`."""
    from django.conf import settings

    served = Path(settings.MEDIA_ROOT) / image_rel
    served.parent.mkdir(parents=True, exist_ok=True)
    served.write_bytes(b"jp2-bytes")
    image: ItemImage = ItemImage.objects.create(
        item_part=item_part or ItemPartFactory(),
        image=image_rel,
    )
    return image


def test_delete_removes_the_served_file(settings, django_capture_on_commit_callbacks):
    image = _make_image(image_rel="uploads/item-part-1/f1r.jp2")
    served = Path(settings.MEDIA_ROOT) / "uploads/item-part-1/f1r.jp2"
    assert served.exists()

    with django_capture_on_commit_callbacks(execute=True):
        image.delete()

    assert not served.exists()
    # Emptied per-part directories are pruned, root survives.
    assert not served.parent.exists()
    assert Path(settings.MEDIA_ROOT).exists()


def test_delete_via_management_api_removes_file(settings, management_client, django_capture_on_commit_callbacks):
    image = _make_image(image_rel="uploads/item-part-2/f2r.jp2")
    served = Path(settings.MEDIA_ROOT) / "uploads/item-part-2/f2r.jp2"

    with django_capture_on_commit_callbacks(execute=True):
        resp = management_client.delete(f"/api/v1/manuscripts/management/item-images/{image.pk}/")

    assert resp.status_code == 204
    assert not served.exists()
    assert not ItemImage.objects.filter(pk=image.pk).exists()


def test_item_part_cascade_deletes_files(settings, django_capture_on_commit_callbacks):
    part = ItemPartFactory()
    image = _make_image(image_rel="uploads/item-part-9/a.jp2", item_part=part)
    served = Path(settings.MEDIA_ROOT) / "uploads/item-part-9/a.jp2"
    assert served.exists()

    with django_capture_on_commit_callbacks(execute=True):
        part.delete()  # cascades to its ItemImages

    assert not ItemImage.objects.filter(pk=image.pk).exists()
    assert not served.exists()


def test_shared_served_path_is_kept(settings, django_capture_on_commit_callbacks):
    # Two rows pointing at one file (no unique constraint on image).
    shared = "shared/dup.jp2"
    first = _make_image(image_rel=shared)
    ItemImage.objects.create(item_part=ItemPartFactory(), image=shared)
    served = Path(settings.MEDIA_ROOT) / shared

    with django_capture_on_commit_callbacks(execute=True):
        first.delete()

    # The surviving row still needs the file.
    assert served.exists()


def test_missing_file_delete_is_noop(settings, django_capture_on_commit_callbacks):
    image = ItemImage.objects.create(item_part=ItemPartFactory(), image="uploads/gone/nofile.jp2")
    with django_capture_on_commit_callbacks(execute=True):
        image.delete()  # must not raise
    assert not ItemImage.objects.filter(pk=image.pk).exists()


def test_traversal_path_is_refused(settings, tmp_path, django_capture_on_commit_callbacks):
    # A crafted path that would escape MEDIA_ROOT must not delete outside it.
    sentinel = tmp_path / "outside.jp2"
    sentinel.write_bytes(b"do-not-delete")
    image = ItemImage.objects.create(item_part=ItemPartFactory(), image="../outside.jp2")

    with django_capture_on_commit_callbacks(execute=True):
        image.delete()

    assert sentinel.exists()  # containment guard refused the delete
