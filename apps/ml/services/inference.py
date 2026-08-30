"""Application service: orchestrates one inference and owns Celery dispatch.

The two halves are deliberately separate. `submit` runs in the request path: it
opens a ledger row, checks the caps, and enqueues. `run` runs in the worker: it
resolves the provider and records the outcome. Nothing in between can reach the
canonical record — this app imports no domain app, and the boundary checker
keeps it that way.
"""

from collections.abc import Iterable, Mapping
import logging
import time
from typing import Any

from django.conf import settings
from django.db import transaction

from ..models import MLJob
from ..providers import (
    InferenceRequest,
    InferenceResult,
    ProviderError,
    ProviderRegistration,
    content_digest,
    resolve_provider,
)
from . import budget, ledger

logger = logging.getLogger(__name__)


class InferenceService:
    """Submit inferences and run them. The only caller of the providers."""

    def submit(
        self,
        *,
        task: str,
        provider: str,
        inputs: Mapping[str, Any],
        params: Mapping[str, Any] | None = None,
        actor: Any | None = None,
    ) -> MLJob:
        """Open a ledger row and enqueue the work. Returns the row either way.

        A refused call still returns a job — refusals are ledger rows, not
        exceptions to the caller, so that a caller cannot swallow one silently.
        """
        registration = resolve_provider(provider)
        actor_id = getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None

        job = ledger.open_job(
            task=task,
            provider=registration.name,
            inputs=inputs,
            params=params,
            actor=actor,
            input_ref=content_digest(inputs),
        )

        try:
            self._check_policy(registration, actor_id=actor_id, task=task)
        except budget.BudgetExceeded as exc:
            logger.warning("Inference refused for task %s: %s", task, exc)
            return ledger.record_refusal(job, str(exc))

        # Enqueue only once the row is committed: a worker that picks the job up
        # before its transaction lands would read a row that does not exist yet.
        transaction.on_commit(lambda: self._dispatch(job.pk, inputs, params))
        return job

    def run(
        self,
        job_id: int,
        *,
        inputs: Mapping[str, Any],
        params: Mapping[str, Any] | None = None,
        celery_task_id: str = "",
    ) -> MLJob:
        """Execute the provider for an opened job and close the ledger row."""
        job: MLJob = MLJob.objects.get(pk=job_id)
        registration = resolve_provider(job.provider)
        provider = registration.factory()
        request = InferenceRequest(task=job.task, inputs=inputs, params=params or {})

        ledger.mark_running(job, celery_task_id=celery_task_id)
        started = time.monotonic()
        try:
            result = provider.run(request)
        except ProviderError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            logger.warning("Inference failed for job %s (%s): %s", job.pk, job.task, exc)
            return ledger.record_failure(job, str(exc), duration_ms=elapsed)

        elapsed = int((time.monotonic() - started) * 1000)
        job = ledger.record_success(job, result, duration_ms=elapsed, targets=self._targets(result))
        logger.info(
            "Inference %s succeeded for job %s in %dms (%d micros).",
            job.task,
            job.pk,
            elapsed,
            job.cost_micros,
        )
        return job

    @staticmethod
    def _check_policy(registration: ProviderRegistration, *, actor_id: int | None, task: str) -> None:
        """Data policy first, then spend.

        A hosted provider sends corpus material off our infrastructure, so it is
        gated separately from cost and defaults to off.
        """
        if registration.hosted and not getattr(settings, "ML_HOSTED_PROVIDERS_ENABLED", False):
            raise budget.BudgetExceeded(
                f"Provider '{registration.name}' is hosted and ML_HOSTED_PROVIDERS_ENABLED is off."
            )
        budget.check(task=task, actor_id=actor_id)

    @staticmethod
    def _dispatch(job_id: int, inputs: Mapping[str, Any], params: Mapping[str, Any] | None) -> None:
        # Imported here, not at module scope: the task module imports this
        # service, and a module-level import back would be circular.
        from ..tasks import run_inference

        run_inference.delay(job_id, dict(inputs), dict(params or {}))

    @staticmethod
    def _targets(result: InferenceResult) -> Iterable[tuple[str, int]]:
        """Targets a provider declares in its output, if any.

        Providers do not write canonical records — nothing here can. A provider
        may only *name* the records its output is about, and the ledger records
        the claim.
        """
        declared = result.output.get("targets") if isinstance(result.output, Mapping) else None
        if not isinstance(declared, list):
            return ()
        return [
            (str(item["type"]), int(item["id"]))
            for item in declared
            if isinstance(item, Mapping) and "type" in item and "id" in item
        ]
