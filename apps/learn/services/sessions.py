"""Starting a lesson and asking it a question: what the request path does.

The tutor itself runs in a worker (`tasks`): a lesson takes minutes, and no
request waits on a model. What happens here is everything that can be
refused at once, in the order it is cheapest to refuse it: the switches, who
may upload, the requester's daily allowance, and the picture itself.
"""

from datetime import timedelta
import logging
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.manuscripts.models import ItemImage

from ..models import TutorSession
from . import pictures, tools, tutor

logger = logging.getLogger(__name__)

QUOTA_WINDOW = timedelta(hours=24)
MAX_QUESTION = 2000
UPLOADS_ANYONE = "anyone"
UPLOADS_SIGNED_IN = "signed-in"
UPLOADS_NOBODY = "nobody"


class LearnError(Exception):
    """The request was declined. `str()` is fit to show the student, `code` names it for a site's own words."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


class Unavailable(LearnError):
    """The tutor is switched off."""


class NotAllowed(LearnError):
    """This requester may not do this."""


class QuotaReached(LearnError):
    """This requester has used their allowance."""


class Busy(LearnError):
    """The tutor is still working on this session."""


class Invalid(LearnError):
    """The request cannot be met as made."""


def _signed_in(actor: Any) -> bool:
    return bool(getattr(actor, "is_authenticated", False))


def enabled() -> bool:
    return bool(settings.ML_INFERENCE_ENABLED and settings.ML_HOSTED_PROVIDERS_ENABLED)


def may_upload(actor: Any) -> bool:
    policy = settings.LEARN_UPLOADS
    return policy == UPLOADS_ANYONE or (policy == UPLOADS_SIGNED_IN and _signed_in(actor))


def status(actor: Any) -> dict[str, Any]:
    """What the tutor can do for this requester, for the page to say before anyone waits."""
    return {
        "enabled": enabled(),
        "uploads": settings.LEARN_UPLOADS,
        "may_upload": may_upload(actor),
        "daily_sessions": settings.LEARN_DAILY_SESSIONS,
        "questions_per_session": settings.LEARN_QUESTIONS_PER_SESSION,
        "retention_days": settings.LEARN_RETENTION_DAYS,
        "languages": sorted(tutor.LANGUAGES),
    }


def _started_today(*, actor: Any, requester_key: str) -> int:
    # A lesson that never came should not use up the student's day.
    recent = TutorSession.objects.filter(created__gte=timezone.now() - QUOTA_WINDOW).exclude(
        status__in=[TutorSession.Status.FAILED, TutorSession.Status.REFUSED]
    )
    if _signed_in(actor):
        return int(recent.filter(actor=actor).count())
    return int(recent.filter(actor__isnull=True, requester_key=requester_key).count())


def suggested_pages(limit: int = 12) -> list[ItemImage]:
    """Corpus pages to learn from: those experts annotated most, which give the richest lessons."""
    ranked = (
        tools.public_glyphs()
        .order_by()
        .values("item_image")
        .annotate(n=Count("id"))
        .order_by("-n", "item_image")[:limit]
    )
    order = [row["item_image"] for row in ranked]
    pages = ItemImage.objects.select_related("item_part__historical_item__date").in_bulk(order)
    return [pages[pk] for pk in order if pk in pages]


def start(
    *,
    actor: Any,
    requester_key: str,
    page: ItemImage | None = None,
    upload: bytes | None = None,
    language: str = "en",
) -> TutorSession:
    """Open a session for a corpus page or an uploaded picture, and queue its lesson."""
    if (page is None) == (upload is None):
        raise Invalid("Choose a corpus page or send a picture, not both.")
    if not enabled():
        raise Unavailable(tutor.UNAVAILABLE, "tutor_unavailable")
    if upload is not None and not may_upload(actor):
        if settings.LEARN_UPLOADS == UPLOADS_SIGNED_IN:
            raise NotAllowed("Sign in to learn from your own pictures.")
        raise NotAllowed("The tutor does not take pictures of your own here; choose a corpus page.")
    if _started_today(actor=actor, requester_key=requester_key) >= settings.LEARN_DAILY_SESSIONS:
        raise QuotaReached(
            f"You have started {settings.LEARN_DAILY_SESSIONS} lessons in the last day. Please try again later.",
            "lesson_quota",
        )

    session = TutorSession(
        item_image=page,
        uploaded=upload is not None,
        actor=actor if _signed_in(actor) else None,
        requester_key=requester_key[:64],
        language=language if language in tutor.LANGUAGES else "en",
    )
    if upload is not None:
        try:
            picture = pictures.from_upload(upload)
        except pictures.PictureRefused as exc:
            raise Invalid(str(exc)) from exc
        session.picture.save(f"{session.pk}.jpg", ContentFile(picture.jpeg), save=False)
        session.width, session.height = picture.width, picture.height
    session.save()
    _dispatch_lesson(session)
    return session


def ask(session: TutorSession, question: str, *, actor: Any, requester_key: str) -> TutorSession:
    """Put the student's question to the tutor, if they may ask it now."""
    question = (question or "").strip()
    if not question:
        raise Invalid("Ask a question.")
    if len(question) > MAX_QUESTION:
        raise Invalid(f"Questions are limited to {MAX_QUESTION} characters.")
    if not enabled():
        raise Unavailable(tutor.UNAVAILABLE, "tutor_unavailable")
    with transaction.atomic():
        locked: TutorSession = TutorSession.objects.select_for_update().get(pk=session.pk)
        if not locked.started_by(actor=actor, requester_key=requester_key):
            raise NotAllowed("Only the student who started this lesson can ask it questions.")
        if locked.status in (TutorSession.Status.QUEUED, TutorSession.Status.WORKING):
            raise Busy("The tutor is still working; wait for it to finish.")
        if locked.status != TutorSession.Status.READY:
            raise Invalid("This lesson did not finish, so it cannot be asked questions.")
        asked = sum(1 for message in locked.messages if message.get("role") == "student")
        if asked >= settings.LEARN_QUESTIONS_PER_SESSION:
            raise QuotaReached(
                f"A lesson takes {settings.LEARN_QUESTIONS_PER_SESSION} questions; start another.",
                "lesson_questions",
            )
        locked.messages.append({"role": "student", "text": question, "at": timezone.now().isoformat()})
        locked.status = TutorSession.Status.WORKING
        locked.save()
        transaction.on_commit(lambda: _dispatch_answer(locked))
    return locked


def _dispatch_lesson(session: TutorSession) -> None:
    from ..tasks import write_lesson

    transaction.on_commit(lambda: write_lesson.delay(str(session.pk)))


def _dispatch_answer(session: TutorSession) -> None:
    from ..tasks import answer_question

    answer_question.delay(str(session.pk))
