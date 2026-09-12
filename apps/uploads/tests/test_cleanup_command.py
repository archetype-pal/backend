from datetime import timedelta
import io

from django.core.management import call_command
from django.utils import timezone
import pytest

from apps.uploads.models import ImageUploadSession
from apps.uploads.tests.factories import ImageUploadSessionFactory

pytestmark = pytest.mark.django_db


def test_cleanup_stale_uploads_command():
    stale = ImageUploadSessionFactory()
    ImageUploadSession.objects.filter(pk=stale.pk).update(modified=timezone.now() - timedelta(days=30))
    fresh = ImageUploadSessionFactory()

    out = io.StringIO()
    call_command("cleanup_stale_uploads", "--days", "7", stdout=out)

    assert "Removed 1 stale upload session(s) and 0 orphan temp dir(s)." in out.getvalue()
    assert set(ImageUploadSession.objects.values_list("pk", flat=True)) == {fresh.pk}
