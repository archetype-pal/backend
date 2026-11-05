"""W1.4 — drafting one page's transcription, when a user asks for it.

Drafting is a user's decision, page by page (decided November 2026). The
hosted reader meets §7.2's target over the transcribed pages, but the
untranscribed tail is not drafted in bulk: a user picks a page in the
backoffice and asks. A worker then reads the page with the reader as it was
measured (see `htr`) and files what it reads as a Draft transcription, marked
machine-drafted in its TEI, for review like any other.

The request refuses at once what it can, cheapest first: inference switched
off, a spend cap reached, a page that has a transcription, or one already
being drafted. The worker checks the switches and caps again, as every
inference does, and the transcription again: someone may have written one
while the page was being read, and theirs stands.
"""

from datetime import timedelta
import logging
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.manuscripts.models import ImageText, ItemImage
from apps.ml.services import BudgetExceeded, budget

from ..models import PageDraft
from . import htr

logger = logging.getLogger(__name__)

# The reader as measured in November 2026: Claude Fable 5.1 asked for the
# edition's text, the page at up to 2,576 pixels, with high effort. Median CER
# 0.062 over 180 transcribed pages, at about $0.28 a page.
READER: dict[str, Any] = {
    "provider": "claude",
    "model": "claude-fable-5-1",
    "size": 2576,
    "effort": "high",
    "max_tokens": 32000,
    "style": htr.EDITED,
}
# A page takes a minute or two. The worker is stopped well past that, and a
# draft still unfinished after it is taken to have been abandoned.
TIME_LIMIT = 900
ABANDONED_AFTER = timedelta(seconds=TIME_LIMIT + 120)

UNAVAILABLE = "Drafting with a model is switched off on this server."
WRITTEN_MEANWHILE = "Someone transcribed this page while it was being read; their transcription stands."
FAILURES = {
    "unavailable": "The page's image could not be fetched for the model.",
    "unparsable": "The model's answer could not be read as lines of text.",
}


class DraftError(Exception):
    """The request was declined. `str()` is fit to show the user."""


class Unavailable(DraftError):
    """Drafting is switched off."""


class CapReached(DraftError):
    """A spend cap would be passed."""


class Transcribed(DraftError):
    """The page has a transcription already."""

    def __init__(self, text: ImageText):
        super().__init__("This page already has a transcription.")
        self.text = text


class Busy(DraftError):
    """The page is being drafted already."""

    def __init__(self, draft: PageDraft):
        super().__init__("This page is already being drafted.")
        self.draft = draft


def enabled() -> bool:
    return bool(settings.ML_INFERENCE_ENABLED and settings.ML_HOSTED_PROVIDERS_ENABLED)


def _actor_id(actor: Any) -> int | None:
    return getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None


def request_draft(image: ItemImage, *, actor: Any) -> PageDraft:
    """Queue a draft of this page's transcription, if it may be drafted now."""
    if not enabled():
        raise Unavailable(UNAVAILABLE)
    try:
        budget.check(task=htr.TASK, actor_id=_actor_id(actor))
    except BudgetExceeded as exc:
        raise CapReached(f"Drafting is paused: {exc}") from exc

    text = ImageText.objects.filter(item_image_id=image.pk, type=ImageText.Type.TRANSCRIPTION).first()
    if text is not None:
        raise Transcribed(text)

    PageDraft.objects.filter(
        item_image_id=image.pk, status__in=PageDraft.ACTIVE, updated__lt=timezone.now() - ABANDONED_AFTER
    ).update(status=PageDraft.Status.FAILED, error="The reading stopped without finishing.", updated=timezone.now())
    try:
        with transaction.atomic():
            draft: PageDraft = PageDraft.objects.create(
                item_image=image, requested_by_id=_actor_id(actor), status=PageDraft.Status.QUEUED
            )
    except IntegrityError:
        active = PageDraft.objects.filter(item_image_id=image.pk, status__in=PageDraft.ACTIVE).first()
        if active is None:
            raise
        raise Busy(active) from None

    transaction.on_commit(lambda: _dispatch(draft.pk))
    return draft


def _dispatch(draft_id: int) -> None:
    from ..tasks import draft_page as task

    task.delay(draft_id)


def _stop(draft: PageDraft, error: str, *, refused: bool = False) -> PageDraft:
    draft.status = PageDraft.Status.REFUSED if refused else PageDraft.Status.FAILED
    draft.error = error
    draft.save(update_fields=["status", "error", "ml_job", "updated"])
    return draft


def draft_page(draft_id: int) -> PageDraft:
    """Read the page and file its draft. Runs in a worker."""
    draft: PageDraft = PageDraft.objects.select_related("item_image", "requested_by").get(pk=draft_id)
    if draft.status != PageDraft.Status.QUEUED:
        logger.warning("Page draft %s is %s; not reading it again.", draft.pk, draft.status)
        return draft
    draft.status = PageDraft.Status.WORKING
    draft.save(update_fields=["status", "updated"])

    try:
        job, payload, outcome = htr.read_page(draft.item_image, actor=draft.requested_by, **READER)
    except Exception:
        # The ledger has the cause, and Celery the traceback. The row must not
        # stay `working`, or the page could not be asked for again until it
        # was taken to have been abandoned.
        _stop(draft, "The reading stopped before it finished.")
        raise
    draft.ml_job = job

    if outcome == "refused":
        return _stop(draft, f"The model was not asked: {job.error if job else UNAVAILABLE}", refused=True)
    if outcome != "ok" or payload is None or job is None:
        reason = FAILURES.get(outcome) or f"The model call failed: {job.error if job else outcome}"
        return _stop(draft, reason)

    try:
        with transaction.atomic():
            text = htr.file_draft(draft.item_image_id, payload, model=job.model_name or READER["model"])
    except IntegrityError:
        text = None
    if text is None:
        return _stop(draft, WRITTEN_MEANWHILE)

    draft.image_text = text
    draft.drafted_content = text.content
    draft.status = PageDraft.Status.DRAFTED
    draft.error = ""
    draft.save()
    return draft
