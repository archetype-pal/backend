from datetime import timedelta

from django.utils import timezone
import pytest

from apps.common.tests.commands import run_command
from apps.uploads.models import ImageUploadSession
from apps.uploads.tests.factories import ImageUploadSessionFactory

pytestmark = pytest.mark.django_db


def test_cleanup_stale_uploads_command():
    stale = ImageUploadSessionFactory()
    ImageUploadSession.objects.filter(pk=stale.pk).update(modified=timezone.now() - timedelta(days=30))
    fresh = ImageUploadSessionFactory()

    out = run_command("cleanup_stale_uploads", "--days", "7")

    assert "Removed 1 stale upload session(s) and 0 orphan temp dir(s)." in out
    assert set(ImageUploadSession.objects.values_list("pk", flat=True)) == {fresh.pk}
