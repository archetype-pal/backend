"""W4.4 — the palaeography tutor's sessions.

A session is one student's walkthrough of one picture, and the conversation
that follows it. Its id is a UUID because the session's address is the only
key to it: a student needs no account to learn from a corpus page, so whoever
has the link may read the lesson. Only the requester who started it may ask
it more.
"""

import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils.deconstruct import deconstructible


@deconstructible
class PictureStorage(FileSystemStorage):
    """The private store for the pictures the tutor sees, at `LEARN_STORAGE_DIR`.

    Outside MEDIA_ROOT, which nginx and SIPI serve by path: a student's upload
    must be reachable only through its session. The location is read from the
    setting on every use rather than once, as Django's own default storage is.
    """

    @property
    def base_location(self) -> str:
        return str(settings.LEARN_STORAGE_DIR)

    @property
    def location(self) -> str:
        return os.path.abspath(self.base_location)


picture_storage = PictureStorage()


def _picture_storage() -> FileSystemStorage:
    return picture_storage


class TutorSession(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        WORKING = "working", "Working"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        REFUSED = "refused", "Refused"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The corpus page it is of, or none for a student's own picture.
    item_image = models.ForeignKey(
        "manuscripts.ItemImage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded = models.BooleanField(default=False)
    # The picture exactly as the tutor saw it. Every box in the lesson is in its pixels.
    picture = models.FileField(storage=_picture_storage, upload_to="sessions/")
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # A salted digest of the requester's address, as the public agent keeps:
    # enough to tell two requesters apart, not to say who either is.
    requester_key = models.CharField(max_length=64, blank=True, default="", db_index=True)

    # The language the student reads the lesson in, as the site's locale names it.
    language = models.CharField(max_length=8, default="en")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    # Why the lesson stopped, in words fit for the student; the cause is logged.
    error = models.TextField(blank=True, default="")
    # What the conversation is held to from its first turn to its last: the
    # model, the system prompt and the tools. The API checks replayed thinking
    # against all three, so a session keeps the ones it started with even if
    # the code or the taxonomy changes under it.
    setup = models.JSONField(default=dict, blank=True)
    # The lesson, once written: an overview, steps that each point at the
    # picture, and a line to practise on.
    walkthrough = models.JSONField(default=dict, blank=True)
    # The conversation as the student sees it: `{"role", "text", "boxes", "at"}`.
    messages = models.JSONField(default=list, blank=True)
    # The conversation as the model saw it, to continue it unchanged. The
    # picture itself is not repeated here; it is put back in when replayed.
    transcript = models.JSONField(default=list, blank=True)
    # What the tutor has done so far, shown while the student waits.
    progress = models.JSONField(default=list, blank=True)
    # Glyphs a tool has shown the tutor. The only ones a lesson may cite.
    seen_glyphs = models.JSONField(default=list, blank=True)
    turns = models.PositiveIntegerField(default=0)
    cost_micros = models.BigIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"Tutor session {self.pk} ({self.status})"

    def started_by(self, *, actor: object, requester_key: str) -> bool:
        """Whether this requester is the one who started the session."""
        if self.actor_id is not None:
            return bool(getattr(actor, "is_authenticated", False) and getattr(actor, "pk", None) == self.actor_id)
        return bool(requester_key) and requester_key == self.requester_key
