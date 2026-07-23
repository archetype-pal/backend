"""Celery task for the upload-ingest pipeline."""

import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task

from apps.uploads.ingest import ingest_session

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def ingest_upload(self: Task, session_id: str) -> dict[str, Any]:
    """Convert, verify and register one assembled upload session.

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
