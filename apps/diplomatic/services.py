"""Running a pipeline, and deciding what it proposed.

The runner is deliberately the only caller of the inference service in this app.
Every pipeline therefore inherits the ledger, the spend caps and the data-policy
gate without doing anything, and no item can quietly acquire its own path to a
model.
"""

import json
import logging
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.diplomatic.models import Proposal
from apps.diplomatic.pipelines.base import Pipeline, Unit, resolve
from apps.ml.services import InferenceService

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "openrouter"

# Models fence JSON as often as not; strip one fence rather than fail a whole
# corpus pass on punctuation.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


class PipelineError(Exception):
    """A pipeline could not run, or its result could not be used."""


def parse_json(text: str) -> Any:
    """Parse a model's JSON answer, tolerating a code fence."""
    fenced = _FENCE.match(text or "")
    payload = fenced.group(1) if fenced else (text or "")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model did not return usable JSON: {exc}") from exc


def run(
    key: str,
    *,
    limit: int | None = None,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    actor: Any | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Run one pipeline over its selection. Returns a per-outcome tally.

    `dry_run` renders the prompts and touches no model, which is how a pipeline
    is inspected before it is pointed at 899 charters.
    """
    pipeline = resolve(key)
    service = InferenceService()
    tally = {"selected": 0, "proposed": 0, "refused": 0, "failed": 0, "unparsable": 0}

    for unit in pipeline.select():
        if limit is not None and tally["selected"] >= limit:
            break
        tally["selected"] += 1

        system, prompt = pipeline.prompt(unit)
        if dry_run:
            logger.info("[dry run] %s on %s#%s\n%s", key, unit.source_type, unit.source_id, prompt[:2000])
            continue

        job = service.submit(
            task=key,
            provider=provider,
            inputs={
                "system": system,
                "prompt": prompt,
                "model": model or pipeline.model,
                "max_tokens": pipeline.max_tokens,
            },
            actor=actor,
            # This loop runs the job itself; enqueueing it as well would race a
            # Celery worker for the same row and bill one of the two for nothing.
            dispatch=False,
        )
        # The service returns the row either way; a refusal is a ledger entry,
        # not an exception, so a capped or gated run stops visibly.
        if job.status == job.Status.REFUSED:
            tally["refused"] += 1
            logger.warning("Pipeline %s refused: %s", key, job.error)
            break

        job = service.run(
            job.pk,
            inputs={
                "system": system,
                "prompt": prompt,
                "model": model or pipeline.model,
                "max_tokens": pipeline.max_tokens,
            },
        )
        if job.status != job.Status.SUCCEEDED:
            tally["failed"] += 1
            continue

        try:
            payload = pipeline.parse(str(job_output(job)))
        except ValueError as exc:
            # The call was made and billed; a bad answer is not a lost cost.
            tally["unparsable"] += 1
            logger.warning("Pipeline %s could not parse job %s: %s", key, job.pk, exc)
            continue

        Proposal.objects.create(
            pipeline=key,
            source_type=unit.source_type,
            source_id=unit.source_id,
            payload=payload,
            ml_job=job,
        )
        tally["proposed"] += 1

    return tally


def job_output(job: Any) -> str:
    """The text a completed job produced.

    The ledger stores no output — deliberately, it would be a second copy of
    corpus-derived material — so the runner reads it from the result it was
    handed. Kept as a seam so a future pipeline can override where text
    comes from.
    """
    return getattr(job, "_output_text", "") or ""


@transaction.atomic
def accept(proposal: Proposal, *, reviewer) -> list[Any]:
    """Promote a proposal to canonical rows, on a named human's authority."""
    if not getattr(reviewer, "is_authenticated", False):
        raise PipelineError("Accepting a proposal requires an authenticated reviewer.")

    locked = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != Proposal.Status.PENDING:
        raise PipelineError(f"Proposal {proposal.pk} is already {locked.status}.")

    pipeline: Pipeline = resolve(locked.pipeline)
    created = pipeline.materialise(locked, reviewer=reviewer)

    locked.status = Proposal.Status.ACCEPTED
    locked.reviewer = reviewer
    locked.reviewed = timezone.now()
    locked.save(update_fields=["status", "reviewer", "reviewed"])
    proposal.status = locked.status
    return created


def reject(proposal: Proposal, *, reviewer, reason: str = "") -> Proposal:
    if not getattr(reviewer, "is_authenticated", False):
        raise PipelineError("Rejecting a proposal requires an authenticated reviewer.")
    if proposal.status != Proposal.Status.PENDING:
        raise PipelineError(f"Proposal {proposal.pk} is already {proposal.status}.")

    proposal.status = Proposal.Status.REJECTED
    proposal.reviewer = reviewer
    proposal.reviewed = timezone.now()
    proposal.reason = reason[:2000]
    proposal.save(update_fields=["status", "reviewer", "reviewed", "reason"])
    return proposal


def queue_depth(pipeline: str = "") -> int:
    """Undecided proposals — what §8.6's reviewer-capacity stop rule reads."""
    queryset = Proposal.objects.filter(status=Proposal.Status.PENDING)
    if pipeline:
        queryset = queryset.filter(pipeline=pipeline)
    return int(queryset.count())


__all__ = ["PipelineError", "Unit", "accept", "parse_json", "queue_depth", "reject", "run"]
