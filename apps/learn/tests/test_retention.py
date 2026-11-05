"""How long a lesson is kept, and that its pictures go with it."""

from datetime import timedelta
import io

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone
import pytest

from apps.learn.models import TutorSession, picture_storage
from apps.learn.services import retention, tutor

pytestmark = pytest.mark.django_db


def _session(*, age_days=0, status=TutorSession.Status.READY, idle_seconds=0) -> TutorSession:
    session = TutorSession(status=status)
    session.picture.save(f"{session.pk}.jpg", ContentFile(b"picture"), save=False)
    session.save()
    picture_storage.save(f"sessions/{session.pk}/look_closer-1.jpg", ContentFile(b"look"))
    TutorSession.objects.filter(pk=session.pk).update(
        created=timezone.now() - timedelta(days=age_days),
        updated=timezone.now() - timedelta(seconds=idle_seconds),
    )
    session.refresh_from_db()
    return session


def test_a_session_past_its_retention_is_deleted_with_every_picture_it_holds(settings):
    settings.LEARN_RETENTION_DAYS = 30
    old, recent = _session(age_days=31), _session(age_days=29)

    pruned = retention.prune()

    assert pruned.deleted == 1
    assert list(TutorSession.objects.values_list("pk", flat=True)) == [recent.pk]
    assert not picture_storage.exists(old.picture.name)
    assert not picture_storage.exists(f"sessions/{old.pk}")
    assert picture_storage.exists(recent.picture.name)
    assert picture_storage.exists(f"sessions/{recent.pk}/look_closer-1.jpg")


def test_a_session_no_worker_will_finish_is_closed(settings):
    settings.LEARN_TIME_LIMIT = 100
    stuck = _session(status=TutorSession.Status.WORKING, idle_seconds=201)
    busy = _session(status=TutorSession.Status.WORKING, idle_seconds=150)

    assert retention.prune().closed == 1

    stuck.refresh_from_db()
    busy.refresh_from_db()
    assert stuck.status == TutorSession.Status.FAILED
    assert stuck.error == tutor.FAILED
    assert busy.status == TutorSession.Status.WORKING


def test_the_command_reports_what_it_did_and_a_dry_run_does_nothing(settings):
    settings.LEARN_RETENTION_DAYS = 30
    _session(age_days=31)
    out = io.StringIO()

    call_command("prune_tutor_sessions", "--dry-run", stdout=out)
    assert "Would delete 1 sessions" in out.getvalue()
    assert TutorSession.objects.count() == 1

    call_command("prune_tutor_sessions", stdout=out)
    assert "Deleted 1 sessions" in out.getvalue()
    assert TutorSession.objects.count() == 0
