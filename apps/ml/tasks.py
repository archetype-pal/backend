"""Celery tasks for inference.

Thin by design: the task resolves nothing and decides nothing, it hands the job
id to the application service. Inference is slow and occasionally fails, which
is why it belongs here — no request path ever waits on a model.
"""

import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task

from apps.ml.services import InferenceService

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_inference(
    self: Task,
    job_id: int,
    inputs: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one opened `MLJob` through its provider and close the ledger row.

    Inputs travel as task arguments rather than being read back from the ledger:
    the ledger stores a content digest of them, not the corpus material itself.
    """
    job = InferenceService().run(
        job_id,
        inputs=inputs,
        params=params,
        celery_task_id=self.request.id or "",
    )
    return {"action": "inference", "job_id": job.pk, "status": job.status}
