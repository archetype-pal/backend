"""Filesystem cleanup for ItemImage deletions.

Django's FileField deliberately does NOT delete the underlying file when its
row is deleted, and an uploaded image's archived original is tracked only by a
path string. So deleting an ItemImage must explicitly remove both the served
JP2 (under MEDIA_ROOT) and, for uploaded images, the archived original (under
UPLOADS_ORIGINALS_DIR).

Deletion is best-effort and never raises: by the time this runs the row is
gone, so a filesystem hiccup must not surface as a 500. It is also deferred to
`transaction.on_commit`, so files are only removed once the row deletion has
actually committed (a rolled-back delete leaves the files intact).
"""

import logging
from pathlib import Path

from django.conf import settings

from apps.manuscripts.models import ItemImage

logger = logging.getLogger(__name__)


def _safe_unlink_within(root: Path, relative: str) -> None:
    """Delete `root/relative` iff it resolves inside `root`; prune emptied dirs.

    Path containment is enforced so a crafted/legacy `..` path can never make
    this delete outside the media or originals tree.
    """
    if not relative:
        return
    root = root.resolve()
    target = (root / relative).resolve()
    if target == root or not target.is_relative_to(root):
        logger.warning("Refusing to delete '%s' outside root '%s'", target, root)
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete image file '%s'", target, exc_info=True)
        return
    # Prune now-empty parent directories (e.g. uploads/item-part-3/) up to but
    # never including the root itself. Stops at the first non-empty dir.
    parent = target.parent
    while parent != root and parent.is_relative_to(root):
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def delete_item_image_files(image_name: str, original_path: str) -> None:
    """Remove the served JP2 and archived original for a deleted ItemImage.

    Each file is kept if any *surviving* ItemImage still references the same
    path: `ItemImage.image` has no unique constraint, so two rows can share a
    served file, and we must not pull a file out from under a row that remains.
    """
    if image_name and not ItemImage.objects.filter(image=image_name).exists():
        _safe_unlink_within(Path(settings.MEDIA_ROOT), image_name)

    if original_path and not ItemImage.objects.filter(original_path=original_path).exists():
        _safe_unlink_within(Path(settings.UPLOADS_ORIGINALS_DIR), original_path)
