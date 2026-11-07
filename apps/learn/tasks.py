"""Celery tasks for the tutor. Thin: each hands a session id to the service.

A lesson takes minutes, a turn at a time, and is given a time limit well past
what one needs: a worker held by a stuck call must come back.
"""

from celery import shared_task
from django.conf import settings

from apps.learn.services import tutor


@shared_task(soft_time_limit=settings.LEARN_TIME_LIMIT, time_limit=settings.LEARN_TIME_LIMIT + 60)
def write_lesson(session_id: str) -> dict[str, str]:
    session = tutor.write_lesson(session_id)
    return {"action": "lesson", "session": str(session.pk), "status": session.status}


@shared_task(soft_time_limit=settings.LEARN_TIME_LIMIT, time_limit=settings.LEARN_TIME_LIMIT + 60)
def answer_question(session_id: str) -> dict[str, str]:
    session = tutor.answer(session_id)
    return {"action": "answer", "session": str(session.pk), "status": session.status}
