"""How long a lesson is kept, and what is deleted with it.

A lesson keeps the student's picture and every enlargement and example the
tutor looked at. They are kept for `LEARN_RETENTION_DAYS`, so that a student
can come back to a lesson, and no longer: a picture of someone's own is not
the platform's to keep.
"""

from dataclasses import dataclass
from datetime import timedelta
import logging
import os

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from ..models import TutorSession, picture_storage
from . import tutor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pruned:
    deleted: int
    closed: int


def expired() -> QuerySet[TutorSession]:
    return TutorSession.objects.filter(created__lt=timezone.now() - timedelta(days=settings.LEARN_RETENTION_DAYS))


def stale() -> QuerySet[TutorSession]:
    """Sessions still queued or working twice as long after a worker would have given up on them."""
    return TutorSession.objects.filter(
        status__in=[TutorSession.Status.QUEUED, TutorSession.Status.WORKING],
        updated__lt=timezone.now() - timedelta(seconds=2 * settings.LEARN_TIME_LIMIT),
    )


def delete_pictures(session: TutorSession) -> None:
    """Delete every picture a session holds: the student's and each the tutor looked at."""
    folder = f"sessions/{session.pk}"
    if picture_storage.exists(folder):
        _, files = picture_storage.listdir(folder)
        for name in files:
            picture_storage.delete(f"{folder}/{name}")
        # The storage deletes files, not folders.
        try:
            os.rmdir(picture_storage.path(folder))
        except OSError:
            logger.info("Left the folder of tutor session %s in place.", session.pk)
    if session.picture:
        picture_storage.delete(session.picture.name)


def prune() -> Pruned:
    """Delete expired sessions with their pictures, and close the stale ones no worker will finish."""
    closing = stale().exclude(pk__in=expired().values("pk"))
    closed = 0
    # A question no worker will answer: the lesson it was asked of is still good.
    for session in closing.exclude(walkthrough={}):
        tutor.question_failed(session, tutor.FAILED)
        closed += 1
    closed += closing.update(status=TutorSession.Status.FAILED, error=tutor.FAILED, updated=timezone.now())
    deleted = 0
    for session in expired().iterator():
        delete_pictures(session)
        session.delete()
        deleted += 1
    return Pruned(deleted=deleted, closed=closed)
