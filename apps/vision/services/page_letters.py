"""W1.1 — proposing one page's letters, when a user asks for it.

The letter models run on our own server, so a page costs nothing and leaves no
server; but what they find goes to people to review, so a user picks the page
in the backoffice and asks. A worker then finds the page's letters and files
the likeliest as proposals (see `letters.propose_page`), and the review queue
takes it from there.

The request refuses at once what it can: inference switched off, a reader with
no letter models, a spend cap reached, or a page already being worked on. The
worker checks the switches and caps again, as every inference does.
"""

from datetime import timedelta
import logging
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.manuscripts.models import ItemImage
from apps.ml.models import MLJob
from apps.ml.providers.htr_service import installed_letter_models
from apps.ml.services import BudgetExceeded, InferenceService, budget

from ..models import LetterRequest
from . import letters

logger = logging.getLogger(__name__)

# Reading a page and drawing its boxes takes under a minute on a CPU. The
# worker is stopped well past that, and a request still unfinished after it is
# taken to have been abandoned.
TIME_LIMIT = 600
ABANDONED_AFTER = timedelta(seconds=TIME_LIMIT + 120)

UNAVAILABLE = "Proposing letters with a model is switched off on this server."
NO_MODELS = "The reader on this server has no letter models installed."
FAILURES = {
    "unavailable": "The page's image could not be fetched for the models.",
}


class LettersError(Exception):
    """The request was declined. `str()` is fit to show the user."""


class Unavailable(LettersError):
    """Inference is switched off, or the reader cannot propose letters."""


class CapReached(LettersError):
    """A spend cap would be passed."""


class Busy(LettersError):
    """The page's letters are being proposed already."""

    def __init__(self, run: LetterRequest):
        super().__init__("This page's letters are already being proposed.")
        self.run = run


class _Recording(InferenceService):
    """The inference service, remembering the ledger row it opens: the review queue filters by it."""

    job: MLJob | None = None

    def submit(self, **kwargs: Any) -> MLJob:
        self.job = super().submit(**kwargs)
        return self.job


def enabled() -> bool:
    # Self-hosted: the hosted switch does not apply.
    return bool(settings.ML_INFERENCE_ENABLED)


def _actor_id(actor: Any) -> int | None:
    return getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None


def request_letters(image: ItemImage, *, actor: Any) -> LetterRequest:
    """Queue a proposal of this page's letters, if it may run now."""
    if not enabled():
        raise Unavailable(UNAVAILABLE)
    try:
        budget.check(task=letters.TASK, actor_id=_actor_id(actor))
    except BudgetExceeded as exc:
        raise CapReached(f"Proposing letters is paused: {exc}") from exc
    if installed_letter_models() is None:
        raise Unavailable(NO_MODELS)

    close_abandoned(item_image_id=image.pk)
    try:
        with transaction.atomic():
            run: LetterRequest = LetterRequest.objects.create(
                item_image=image, requested_by_id=_actor_id(actor), status=LetterRequest.Status.QUEUED
            )
    except IntegrityError:
        active = LetterRequest.objects.filter(item_image_id=image.pk, status__in=LetterRequest.ACTIVE).first()
        if active is None:
            raise
        raise Busy(active) from None

    transaction.on_commit(lambda: _dispatch(run.pk))
    return run


def close_abandoned(**scope: Any) -> int:
    """Close requests whose worker stopped, which would otherwise show as working."""
    closed: int = LetterRequest.objects.filter(
        status__in=LetterRequest.ACTIVE, updated__lt=timezone.now() - ABANDONED_AFTER, **scope
    ).update(status=LetterRequest.Status.FAILED, error="The models stopped without finishing.", updated=timezone.now())
    return closed


def _dispatch(run_id: int) -> None:
    from ..tasks import propose_page_letters as task

    task.delay(run_id)


def _stop(run: LetterRequest, error: str, *, refused: bool = False) -> LetterRequest:
    run.status = LetterRequest.Status.REFUSED if refused else LetterRequest.Status.FAILED
    run.error = error
    run.save(update_fields=["status", "error", "ml_job", "updated"])
    return run


def propose(run_id: int) -> LetterRequest:
    """Find the page's letters and file the likeliest as proposals. Runs in a worker."""
    run: LetterRequest = LetterRequest.objects.select_related("item_image", "requested_by").get(pk=run_id)
    if run.status != LetterRequest.Status.QUEUED:
        logger.warning("Page letters %s is %s; not running it again.", run.pk, run.status)
        return run
    run.status = LetterRequest.Status.WORKING
    run.save(update_fields=["status", "updated"])

    service = _Recording()
    try:
        tally = letters.propose_page(run.item_image, actor=run.requested_by, service=service)
    except Exception:
        # The ledger has the cause, and Celery the traceback. The row must not
        # stay `working`, or the page could not be asked for again until it
        # was taken to have been abandoned.
        run.ml_job = service.job
        _stop(run, "The models stopped before they finished.")
        raise
    # Read again: the row the service opened was closed by the run since.
    job = MLJob.objects.get(pk=service.job.pk) if service.job else None
    run.ml_job = job

    if tally["refused"]:
        return _stop(run, f"The models were not asked: {job.error if job else UNAVAILABLE}", refused=True)
    if tally["unavailable"]:
        return _stop(run, FAILURES["unavailable"])
    if tally["failed"]:
        return _stop(run, f"The letter models failed: {job.error if job else 'no answer'}")

    run.found = tally["found"]
    run.proposed = tally["proposed"]
    run.status = LetterRequest.Status.PROPOSED
    run.error = ""
    run.save()
    return run
