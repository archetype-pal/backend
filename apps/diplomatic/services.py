"""Running a pipeline, and deciding what it proposed.

The runner is deliberately the only caller of the inference service in this app.
Every pipeline therefore inherits the ledger, the spend caps and the data-policy
gate without doing anything, and no item can quietly acquire its own path to a
model.
"""

from collections.abc import Iterable, Sequence
import copy
import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.diplomatic import network
from apps.diplomatic.models import CharterEntity, Formula, Proposal, Relation
from apps.diplomatic.pipelines.base import PIPELINE_REGISTRY, Pipeline, Unit, resolve
from apps.manuscripts.models import ImageText
from apps.ml.answers import parse_json
from apps.ml.services import InferenceService, ledger

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "openrouter"


class PipelineError(Exception):
    """A pipeline could not run, or its result could not be used."""


class InvalidSelection(PipelineError):
    """The items chosen for a partial acceptance do not fit the proposal."""


# What every current pipeline reads: a charter transcription (`ImageText`), in
# `EditEvent`'s vocabulary.
SOURCE_IMAGETEXT = "imagetext"


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
    tally = {
        "selected": 0,
        "proposed": 0,
        "nothing_found": 0,
        "refused": 0,
        "failed": 0,
        "unparsable": 0,
        "queue_full": 0,
    }

    # Whatever was decided about it, a text already proposed on is not paid for
    # again, and a capped run picks up where the last one stopped.
    done = set(Proposal.objects.filter(pipeline=key).values_list("source_type", "source_id"))

    for unit in pipeline.select():
        if (unit.source_type, unit.source_id) in done:
            continue
        if limit is not None and tally["selected"] >= limit:
            break
        # Per pipeline, as the review queue is: each has its own tab and may have its own reviewers.
        if not dry_run and queue_depth(key) >= settings.ML_REVIEW_LIMIT_CHARTERS:
            tally["queue_full"] = 1
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

        if not pipeline.worth_reviewing(payload):
            tally["nothing_found"] += 1
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


def _selection(proposal: Proposal, pipeline: Pipeline, items: Sequence[int] | None) -> tuple[Proposal, list[int]]:
    """The proposal as its materialiser should see it, and the positions left out.

    `items` are positions in the pipeline's list; None accepts it whole. The
    materialiser is handed a copy holding only the chosen items, so the stored
    payload keeps the model's whole answer for the audit.
    """
    if items is None:
        return proposal, []
    key = pipeline.items_key
    if key is None:
        raise InvalidSelection(f"A {pipeline.key} proposal is one answer: accept or reject it whole.")
    listed = proposal.payload.get(key) or []
    chosen = sorted(set(items))
    if not chosen:
        raise InvalidSelection("Accepting none of the items is a rejection: reject the proposal instead.")
    if chosen[0] < 0 or chosen[-1] >= len(listed):
        raise InvalidSelection(f"Proposal {proposal.pk} lists {len(listed)} {key}, numbered from 0.")
    selection = copy.copy(proposal)
    selection.payload = {**proposal.payload, key: [listed[i] for i in chosen]}
    return selection, [i for i in range(len(listed)) if i not in chosen]


@transaction.atomic
def accept(proposal: Proposal, *, reviewer, items: Sequence[int] | None = None) -> list[Any]:
    """Promote a proposal to canonical rows, on a named human's authority.

    `items` accepts only those positions of a list answer (`Pipeline.items_key`)
    and records the rest as dropped; None accepts everything.
    """
    if not getattr(reviewer, "is_authenticated", False):
        raise PipelineError("Accepting a proposal requires an authenticated reviewer.")

    locked = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != Proposal.Status.PENDING:
        raise PipelineError(f"Proposal {proposal.pk} is already {locked.status}.")
    # `source_id` is a loose pointer, so deleting the text left the proposal
    # behind. Its records would be written against a text that is gone: an
    # integrity error at commit, or a lookup that fails, either way a 500.
    if locked.source_type == SOURCE_IMAGETEXT and not ImageText.objects.filter(pk=locked.source_id).exists():
        raise PipelineError(f"Text {locked.source_id}, which proposal {proposal.pk} was read from, no longer exists.")

    pipeline: Pipeline = resolve(locked.pipeline)
    selection, dropped = _selection(locked, pipeline, items)
    created = pipeline.materialise(selection, reviewer=reviewer)
    if locked.ml_job_id:
        ledger.attach_targets(locked.ml_job, [(row._meta.model_name, row.pk) for row in created])

    locked.status = Proposal.Status.ACCEPTED
    locked.reviewer = reviewer
    locked.reviewed = timezone.now()
    locked.dropped_items = dropped
    locked.save(update_fields=["status", "reviewer", "reviewed", "dropped_items"])
    proposal.status = locked.status
    proposal.dropped_items = dropped
    return created


@transaction.atomic
def reject(proposal: Proposal, *, reviewer, reason: str = "") -> Proposal:
    if not getattr(reviewer, "is_authenticated", False):
        raise PipelineError("Rejecting a proposal requires an authenticated reviewer.")
    # Locked for the reason `accept` is. Checking the caller's copy lets a
    # reject that read `pending` before a concurrent accept committed write
    # `rejected` over it, leaving canonical rows whose proposal says no one
    # accepted it.
    locked = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != Proposal.Status.PENDING:
        raise PipelineError(f"Proposal {proposal.pk} is already {locked.status}.")

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


def pending_by_pipeline() -> dict[str, int]:
    """Undecided proposals per registered pipeline, zeros included.

    Every registered pipeline appears, so the review queue can offer a tab for
    each without hard-coding the list, and a new pipeline shows up on its own.
    """
    counts = dict.fromkeys(sorted(PIPELINE_REGISTRY), 0)
    rows = (
        Proposal.objects.filter(status=Proposal.Status.PENDING)
        .values_list("pipeline")
        .annotate(n=Count("id"))
        .order_by()
    )
    for pipeline, n in rows:
        counts[pipeline] = int(n)
    return counts


def proposal_sources(proposals: Iterable[Proposal]) -> dict[int, ImageText]:
    """The transcriptions a set of proposals was read from, fetched at once.

    `source_id` is a loose pointer rather than a foreign key, so neither
    `select_related` nor a serializer can follow it without a query per row.
    The joins are the ones `ItemImage`'s label walks (`ItemPart.display_label`)
    and the catalogue date W3.2 judged against.
    """
    ids = {p.source_id for p in proposals if p.source_type == SOURCE_IMAGETEXT}
    if not ids:
        return {}
    texts = (
        ImageText.objects.filter(pk__in=ids)
        .select_related(
            "item_image__item_part__current_item__repository",
            "item_image__item_part__historical_item__date",
        )
        .prefetch_related("item_image__item_part__historical_item__catalogue_numbers__catalogue")
    )
    return {text.pk: text for text in texts}


__all__ = [
    "PipelineError",
    "Unit",
    "accept",
    "parse_json",
    "pending_by_pipeline",
    "proposal_sources",
    "queue_depth",
    "reject",
    "run",
]


def readable_texts(user: Any) -> Any:
    """The texts this reader may see, by the same rule as the texts themselves.

    The pipelines read drafts as well as published texts, so an approved record
    can come from a text the public cannot open. Its names, and a formula's
    excerpt above all, are that draft's words. Visibility is decided when the
    record is read, because a text's status can change after approval.
    """
    return ImageText.objects.visible_to(user).values("pk")


def public_network(user: Any) -> network.Graph:
    """The witness and scribe network, from the texts this reader may see."""
    return network.build(readable_texts(user))


def public_summary(user: Any) -> dict[str, int]:
    """How much approved material this reader can see, by kind.

    Read by the site's navigation, which offers the formulary and the network
    only once there is something in them.
    """
    readable = readable_texts(user)
    return {
        "formulae": Formula.objects.filter(occurrences__image_text__in=readable).distinct().count(),
        "entities": CharterEntity.objects.filter(image_text__in=readable).count(),
        "relations": Relation.objects.filter(image_text__in=readable).count(),
    }
