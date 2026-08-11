"""Deleting an ItemImage must remove its files from disk, not just the DB row.

Django's FileField leaves files behind on delete; a post_delete signal
(apps.manuscripts.signals) removes the served JP2 and the archived original.
Deletion is deferred to transaction.on_commit, so these tests execute the
commit hooks via `django_capture_on_commit_callbacks`.
"""

from pathlib import Path

import pytest

from apps.manuscripts.models import ItemImage
from apps.manuscripts.tests.factories import ItemPartFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def originals_dir(settings, tmp_path):
    path = tmp_path / "originals"
    settings.UPLOADS_ORIGINALS_DIR = str(path)
    return path


def _make_image(*, image_rel: str, original_rel: str = "", item_part=None) -> ItemImage:
    """Create an ItemImage with real files on disk at the given relative paths."""
    from django.conf import settings

    served = Path(settings.MEDIA_ROOT) / image_rel
    served.parent.mkdir(parents=True, exist_ok=True)
    served.write_bytes(b"jp2-bytes")
    if original_rel:
        original = Path(settings.UPLOADS_ORIGINALS_DIR) / original_rel
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"tiff-bytes")
    image: ItemImage = ItemImage.objects.create(
        item_part=item_part or ItemPartFactory(),
        image=image_rel,
        original_path=original_rel,
    )
    return image


def test_delete_removes_both_served_and_original(settings, originals_dir, django_capture_on_commit_callbacks):
    image = _make_image(
        image_rel="uploads/item-part-1/f1r.jp2",
        original_rel="uploads/item-part-1/f1r.tif",
    )
    served = Path(settings.MEDIA_ROOT) / "uploads/item-part-1/f1r.jp2"
    original = originals_dir / "uploads/item-part-1/f1r.tif"
    assert served.exists() and original.exists()

    with django_capture_on_commit_callbacks(execute=True):
        image.delete()

    assert not served.exists()
    assert not original.exists()
    # Emptied per-part directories are pruned, root survives.
    assert not served.parent.exists()
    assert Path(settings.MEDIA_ROOT).exists()


def test_delete_via_management_api_removes_file(
    settings, originals_dir, management_client, django_capture_on_commit_callbacks
):
    image = _make_image(image_rel="uploads/item-part-2/f2r.jp2", original_rel="uploads/item-part-2/f2r.tif")
    served = Path(settings.MEDIA_ROOT) / "uploads/item-part-2/f2r.jp2"

    with django_capture_on_commit_callbacks(execute=True):
        resp = management_client.delete(f"/api/v1/manuscripts/management/item-images/{image.pk}/")

    assert resp.status_code == 204
    assert not served.exists()
    assert not ItemImage.objects.filter(pk=image.pk).exists()


def test_item_part_cascade_deletes_files(settings, originals_dir, django_capture_on_commit_callbacks):
    part = ItemPartFactory()
    image = _make_image(image_rel="uploads/item-part-9/a.jp2", item_part=part)
    served = Path(settings.MEDIA_ROOT) / "uploads/item-part-9/a.jp2"
    assert served.exists()

    with django_capture_on_commit_callbacks(execute=True):
        part.delete()  # cascades to its ItemImages

    assert not ItemImage.objects.filter(pk=image.pk).exists()
    assert not served.exists()


def test_shared_served_path_is_kept(settings, originals_dir, django_capture_on_commit_callbacks):
    # Two rows pointing at one file (no unique constraint on image).
    shared = "shared/dup.jp2"
    first = _make_image(image_rel=shared)
    ItemImage.objects.create(item_part=ItemPartFactory(), image=shared)
    served = Path(settings.MEDIA_ROOT) / shared

    with django_capture_on_commit_callbacks(execute=True):
        first.delete()

    # The surviving row still needs the file.
    assert served.exists()


def test_missing_file_delete_is_noop(settings, originals_dir, django_capture_on_commit_callbacks):
    image = ItemImage.objects.create(item_part=ItemPartFactory(), image="uploads/gone/nofile.jp2")
    with django_capture_on_commit_callbacks(execute=True):
        image.delete()  # must not raise
    assert not ItemImage.objects.filter(pk=image.pk).exists()


def test_migrated_row_without_original_only_touches_served(settings, originals_dir, django_capture_on_commit_callbacks):
    image = _make_image(image_rel="bl/add_12345/f1r.jp2")  # original_path=""
    served = Path(settings.MEDIA_ROOT) / "bl/add_12345/f1r.jp2"

    with django_capture_on_commit_callbacks(execute=True):
        image.delete()

    assert not served.exists()


def test_traversal_path_is_refused(settings, originals_dir, tmp_path, django_capture_on_commit_callbacks):
    # A crafted path that would escape MEDIA_ROOT must not delete outside it.
    sentinel = tmp_path / "outside.jp2"
    sentinel.write_bytes(b"do-not-delete")
    image = ItemImage.objects.create(item_part=ItemPartFactory(), image="../outside.jp2")

    with django_capture_on_commit_callbacks(execute=True):
        image.delete()

    assert sentinel.exists()  # containment guard refused the delete
