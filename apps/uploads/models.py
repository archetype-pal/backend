import uuid

from django.conf import settings
from django.db import models


class UploadSession(models.Model):
    """One chunked upload of a single image file targeted at an ItemPart.

    The session is the resume contract: chunk files accumulate under the
    uploads temp dir keyed by this row's UUID, and `received_chunks` tells an
    interrupted client which indexes are still missing. After `finalize` the
    Celery ingest pipeline owns the session until it lands as an ItemImage
    (status `complete`) or records why it could not (`failed`).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        UPLOADING = "uploading", "Uploading"
        ASSEMBLED = "assembled", "Assembled"
        PROCESSING = "processing", "Processing"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_sessions")
    item_part = models.ForeignKey("manuscripts.ItemPart", on_delete=models.CASCADE, related_name="upload_sessions")

    original_filename = models.CharField(max_length=255)
    declared_size = models.BigIntegerField()
    declared_sha256 = models.CharField(max_length=64, blank=True, default="")
    computed_sha256 = models.CharField(max_length=64, blank=True, default="")
    chunk_size = models.PositiveIntegerField()
    received_chunks = models.JSONField(default=list, blank=True)

    # Media-relative path the served .jp2 will occupy. Computed and
    # collision-checked at session creation; it IS the SIPI IIIF identifier.
    destination_path = models.CharField(max_length=200)
    subfolder = models.CharField(max_length=150, blank=True, default="")

    # Descriptive metadata applied to the ItemImage row at ingest.
    locus = models.CharField(max_length=72, blank=True, default="")
    tags = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")
    task_id = models.CharField(max_length=64, blank=True, default="")
    item_image = models.ForeignKey(
        "manuscripts.ItemImage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    ACTIVE_STATUSES = (Status.PENDING, Status.UPLOADING, Status.ASSEMBLED, Status.PROCESSING)

    class Meta:
        ordering = ["-created"]
        indexes = [models.Index(fields=["status", "created"])]

    @property
    def total_chunks(self) -> int:
        return max(1, -(-int(self.declared_size) // int(self.chunk_size)))  # ceil division

    def missing_chunks(self) -> list[int]:
        received = set(self.received_chunks)
        return [i for i in range(self.total_chunks) if i not in received]

    def __str__(self) -> str:
        return f"{self.original_filename} → {self.destination_path} ({self.status})"
