"""Celery task for the upload-ingest pipeline."""

import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task
from django.conf import settings

from apps.uploads.ingest import ingest_session

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    # The soft limit surfaces inside `ingest_session`, which records the
    # timeout on the row; the hard limit is the backstop that kills a wedged
    # worker, after which `cleanup_stale_uploads` reaps the session.
    soft_time_limit=settings.UPLOADS_INGEST_TIME_LIMIT,
    time_limit=settings.UPLOADS_INGEST_TIME_LIMIT + 60,
)
def ingest_upload(self: Task, session_id: str) -> dict[str, Any]:
    """Assemble, convert, verify and register one upload session.

    Progress meta mirrors the search tasks' shape (current/total/message/
    index_done/index_total) so the frontend's task-polling component works
    unchanged.
    """

    def progress(step: int, total: int, message: str) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"current": step, "total": total, "message": message, "index_done": step, "index_total": total},
        )

    payload = ingest_session(session_id, progress=progress)
    logger.info(
        "Ingested upload session %s → ItemImage %s at %s",
        session_id,
        payload["item_image_id"],
        payload["destination"],
    )
    return payload
