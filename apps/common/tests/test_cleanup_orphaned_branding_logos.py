from datetime import timedelta
import io
import os

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.utils import timezone
import pytest

from apps.common.models import AppSettings
from apps.common.services.branding import BRANDING_DIR
from apps.common.views import SITE_FEATURES_KEY_PREFIX

pytestmark = pytest.mark.django_db


def _save_logo(name: str, *, hours_old: int = 0) -> str:
    path = default_storage.save(f"{BRANDING_DIR}/{name}", io.BytesIO(b"fake image bytes"))
    if hours_old:
        stale = (timezone.now() - timedelta(hours=hours_old)).timestamp()
        os.utime(default_storage.path(path), (stale, stale))
    return str(default_storage.url(path))


def _set_referenced_logo(url: str) -> None:
    AppSettings.objects.update_or_create(
        key=f"{SITE_FEATURES_KEY_PREFIX}branding.logoUrl",
        defaults={"value": f'"{url}"', "is_active": True, "is_public": True},
    )


def test_removes_only_stale_unreferenced_files():
    referenced_url = _save_logo("current.png", hours_old=48)
    _set_referenced_logo(referenced_url)
    _save_logo("superseded.png", hours_old=48)
    _save_logo("just-uploaded.png", hours_old=0)

    out = io.StringIO()
    call_command("cleanup_orphaned_branding_logos", "--hours", "24", stdout=out)

    _, remaining = default_storage.listdir(BRANDING_DIR)
    assert set(remaining) == {"current.png", "just-uploaded.png"}
    assert "Removed 1 orphaned branding logo file(s)." in out.getvalue()


def test_no_referenced_logo_leaves_fresh_files_alone():
    _save_logo("abandoned.png", hours_old=0)

    call_command("cleanup_orphaned_branding_logos", "--hours", "24")

    _, remaining = default_storage.listdir(BRANDING_DIR)
    assert remaining == ["abandoned.png"]
