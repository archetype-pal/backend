"""Cleanup for `branding/` logo files (see `BrandingLogoUploadView`).

Every super-admin file selection in "UI customization" uploads immediately
and gets its own filename (`default_storage.save` never overwrites), so a
selection that gets replaced, or never saved at all, just sits in storage
forever. There is no model row a signal could hang a delete off of — the only
record of which file is "live" is the `branding.logoUrl` AppSettings value —
so cleanup is a sweep rather than an on-write delete.
"""

from datetime import timedelta
import json

from django.core.files.storage import default_storage
from django.utils import timezone

from apps.common.models import AppSettings
from apps.common.views import SITE_FEATURES_KEY_PREFIX

BRANDING_DIR = "branding"


def _referenced_filename() -> str | None:
    row = AppSettings.objects.filter(key=f"{SITE_FEATURES_KEY_PREFIX}branding.logoUrl", is_active=True).first()
    if not row:
        return None
    try:
        url = json.loads(row.value)
    except (TypeError, ValueError):  # fmt: skip
        return None
    if not isinstance(url, str) or f"{BRANDING_DIR}/" not in url:
        return None
    return url.rsplit("/", 1)[-1]


def cleanup_orphaned_branding_logos(*, older_than_hours: int) -> dict[str, int]:
    """Delete `branding/` files that aren't the referenced logo, older than `older_than_hours`.

    The age check protects a file uploaded moments ago whose URL hasn't been
    saved into `branding.logoUrl` yet — the two calls (upload, then PUT
    site-features) aren't atomic, so a sweep running in between must not treat
    the in-flight upload as an orphan.
    """
    referenced = _referenced_filename()
    cutoff = timezone.now() - timedelta(hours=older_than_hours)

    try:
        _, filenames = default_storage.listdir(BRANDING_DIR)
    except FileNotFoundError:
        filenames = []

    removed = 0
    for filename in filenames:
        if filename == referenced:
            continue
        path = f"{BRANDING_DIR}/{filename}"
        if default_storage.get_modified_time(path) >= cutoff:
            continue
        default_storage.delete(path)
        removed += 1

    return {"removed": removed}
