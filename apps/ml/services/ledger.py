"""Domain service: the only writer of the inference ledger.

Every state change a job can undergo is a function here, so the ledger's
invariants live in one place: a job is opened before a provider is called, is
closed exactly once, and never loses the record of what it touched.
"""

from collections.abc import Iterable, Mapping
from typing import Any, cast

from django.db import transaction

from ..models import MLJob, MLJobTarget
from ..providers import InferenceResult


def open_job(
    *,
    task: str,
    provider: str,
    inputs: Mapping[str, Any],
    params: Mapping[str, Any] | None = None,
    actor: Any | None = None,
    input_ref: str = "",
) -> MLJob:
    """Record the intent to run an inference, before anything runs.

    Opening first is what makes an abandoned or crashed call visible: a row
    stuck in `pending` is evidence, where a row written only on success would
    have left nothing behind.
    """
    return cast(
        MLJob,
        MLJob.objects.create(
            task=task,
            provider=provider,
            params=dict(params or {}),
            input_ref=input_ref,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            status=MLJob.Status.PENDING,
        ),
    )


def mark_running(job: MLJob, *, celery_task_id: str = "") -> MLJob:
    job.status = MLJob.Status.RUNNING
    job.celery_task_id = celery_task_id or job.celery_task_id
    job.save(update_fields=["status", "celery_task_id"])
    return job


@transaction.atomic
def record_success(
    job: MLJob,
    result: InferenceResult,
    *,
    duration_ms: int,
    targets: Iterable[tuple[str, int]] = (),
) -> MLJob:
    """Close *job* as succeeded and attach the records it touched.

    Atomic with the targets: a job that reports success without its provenance
    is worse than a job that reports failure, because it looks trustworthy.
    """
    job.status = MLJob.Status.SUCCEEDED
    job.model_name = result.model_name
    job.model_version = result.model_version
    job.prompt_hash = result.prompt_hash
    job.input_tokens = result.input_tokens
    job.output_tokens = result.output_tokens
    job.cost_micros = result.cost_micros
    job.cost_currency = result.cost_currency
    job.duration_ms = duration_ms
    job.save(
        update_fields=[
            "status",
            "model_name",
            "model_version",
            "prompt_hash",
            "input_tokens",
            "output_tokens",
            "cost_micros",
            "cost_currency",
            "duration_ms",
        ]
    )
    attach_targets(job, targets)
    return job


def record_failure(job: MLJob, error: str, *, duration_ms: int | None = None) -> MLJob:
    job.status = MLJob.Status.FAILED
    # Truncated: a provider traceback can be unbounded, and the ledger is not a
    # log sink. The full text belongs in the worker log.
    job.error = error[:4000]
    job.duration_ms = duration_ms
    job.save(update_fields=["status", "error", "duration_ms"])
    return job


def record_refusal(job: MLJob, reason: str) -> MLJob:
    """Close *job* as refused — declined before any provider was called."""
    job.status = MLJob.Status.REFUSED
    job.error = reason[:4000]
    job.save(update_fields=["status", "error"])
    return job


def attach_targets(job: MLJob, targets: Iterable[tuple[str, int]]) -> None:
    """Record which canonical records this inference produced or modified."""
    rows = [MLJobTarget(job=job, target_type=target_type, target_id=target_id) for target_type, target_id in targets]
    if rows:
        # ignore_conflicts: re-attaching the same target is idempotent, which
        # matters when a task is retried after a partial write.
        MLJobTarget.objects.bulk_create(rows, ignore_conflicts=True)


def jobs_touching(target_type: str, target_id: int):
    """Every inference that touched a given record, newest first.

    This is the question the ledger exists to answer.
    """
    return MLJob.objects.filter(targets__target_type=target_type, targets__target_id=target_id).distinct()
