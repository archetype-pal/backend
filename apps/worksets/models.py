import uuid

from django.conf import settings
from django.db import models


class Workset(models.Model):
    """A user-saved lightbox collection, citable by a stable public id.

    `payload` stores the frontend's lightbox serialization verbatim
    (``{schema_version, workspaces, images}``) as opaque JSON, so the server
    persists and returns it without needing to understand the client shape.
    """

    class Visibility(models.TextChoices):
        PRIVATE = "Private"
        PUBLIC = "Public"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="worksets",
    )
    # Unguessable, stable id for citable URLs — a UUID rather than a title slug
    # because titles are user-chosen, non-unique, and worksets must not be
    # enumerable.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    # Private by default so nothing leaks; only Public worksets are anonymously
    # citable.
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
    )
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.public_id})"
