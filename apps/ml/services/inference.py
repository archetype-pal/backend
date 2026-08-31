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

        # Snapshot once, before anything reads it. The caller may reuse and
        # mutate its mapping across a batch, and the digest recorded here must
        # describe the same bytes the worker is later handed — otherwise the
        # ledger asserts provenance it does not have.
        payload = dict(inputs)
        options = dict(params or {})

        job = ledger.open_job(
            task=task,
            provider=registration.name,
            inputs=payload,
            params=options,
            actor=actor,
            input_ref=content_digest(payload),
        )

        try:
            self._check_policy(registration, actor_id=actor_id, task=task)
        except budget.BudgetExceeded as exc:
            logger.warning("Inference refused for task %s: %s", task, exc)
            return ledger.record_refusal(job, str(exc))

        # Enqueue only once the row is committed: a worker that picks the job up
        # before its transaction lands would read a row that does not exist yet.
        transaction.on_commit(lambda: self._dispatch(job.pk, payload, options))
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
        if job.status != MLJob.Status.PENDING:
            # Re-running a decided row would overwrite a refusal with a success
            # and bill for it. The ledger is append-only in spirit; leave it.
            logger.warning("Job %s is already %s; not re-running.", job.pk, job.status)
            return job

        registration = resolve_provider(job.provider)

        # Re-check here, not only at submit. Two holes close: an operator who
        # switches inference off still has a queue draining against providers,
        # and the caps sum `cost_micros`, which is only written on completion —
        # so at submit time a burst of in-flight work sums to nothing. Checking
        # in the worker bounds the overshoot to worker concurrency instead of
        # queue depth, because by then earlier spend has settled.
        try:
            self._check_policy(registration, actor_id=job.actor_id, task=job.task)
        except budget.BudgetExceeded as exc:
            logger.warning("Inference refused at execution for job %s: %s", job.pk, exc)
            return ledger.record_refusal(job, str(exc))

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
        except Exception as exc:
            # Not just ProviderError: a provider may fail in any way, and the
            # model has already been called and billed by the time it does. A
            # row left RUNNING with cost 0 hides that spend from every later cap
            # check. Record, then re-raise so Celery and monitoring still see it.
            elapsed = int((time.monotonic() - started) * 1000)
            logger.exception("Inference crashed for job %s (%s)", job.pk, job.task)
            ledger.record_failure(job, f"{type(exc).__name__}: {exc}", duration_ms=elapsed)
            raise

        elapsed = int((time.monotonic() - started) * 1000)
        try:
            targets = self._targets(result)
        except (TypeError, ValueError) as exc:
            # A malformed target claim must not lose the cost of a call that ran.
            logger.warning("Job %s declared unusable targets (%s); recording without them.", job.pk, exc)
            targets = []
        job = ledger.record_success(job, result, duration_ms=elapsed, targets=targets)
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
