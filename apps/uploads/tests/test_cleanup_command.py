from datetime import timedelta
import io

from django.core.management import call_command
from django.utils import timezone
import pytest

from apps.uploads.models import UploadSession
from apps.uploads.tests.factories import UploadSessionFactory

pytestmark = pytest.mark.django_db


def test_cleanup_stale_uploads_command():
    stale = UploadSessionFactory()
    UploadSession.objects.filter(pk=stale.pk).update(modified=timezone.now() - timedelta(days=30))
    fresh = UploadSessionFactory()

    out = io.StringIO()
    call_command("cleanup_stale_uploads", "--days", "7", stdout=out)

    assert "Removed 1 stale upload session(s)." in out.getvalue()
    assert set(UploadSession.objects.values_list("pk", flat=True)) == {fresh.pk}
