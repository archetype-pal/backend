import hashlib
import json
import struct
from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.db import models
from django.db.models.functions import Length

if TYPE_CHECKING:
    from apps.annotations.models import Graph


class GlyphEmbedding(models.Model):
    """One glyph's vector from one self-hosted encoder (AI programme W1.2).

    Written only by `apps.vision.services.embedding`, from what an encoder
    returned through the ledger; `ml_job` is the row that made it. A glyph has
    at most one vector per encoder, so two encoders can be compared side by
    side over the same glyphs.

    The vector is stored as little-endian float32 bytes, which is how every
    reader (a nearest-neighbour search, a search index) wants it. The database
    refuses a vector whose length does not match `dimensions`.

    A vector describes the crop it was made from, so it is stamped with
    `crop_digest`, a digest of the page image and the outline the crop was cut
    from. A glyph that is redrawn, or whose page is given another image, no
    longer has that crop, and its vector is stale: its stamp no longer matches
    `crop_digest_for` the glyph.
    """

    graph = models.ForeignKey("annotations.Graph", on_delete=models.CASCADE, related_name="embeddings")
    # The provider that made it, e.g. "trocr". `model_name` and
    # `model_version` say which weights, as the encoder reported them.
    encoder = models.CharField(max_length=32)
    model_name = models.CharField(max_length=128)
    model_version = models.CharField(max_length=128)
    dimensions = models.PositiveSmallIntegerField()
    vector = models.BinaryField()
    crop_digest = models.CharField(max_length=64)
    ml_job = models.ForeignKey("ml.MLJob", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created = models.DateTimeField(auto_now_add=True)

    BYTES_PER_VALUE: ClassVar[int] = 4

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["graph", "encoder"], name="glyph_embedding_one_per_encoder"),
            models.CheckConstraint(
                condition=models.Q(dimensions__gt=0)
                & models.lookups.Exact(Length("vector"), models.F("dimensions") * 4),
                name="glyph_embedding_vector_fits_dimensions",
            ),
        ]
        indexes = [models.Index(fields=["encoder", "model_version"], name="glyph_embedding_encoder_idx")]

    def __str__(self) -> str:
        return f"Graph {self.graph_id} · {self.encoder}@{self.model_version}"

    @staticmethod
    def pack(values: list[float]) -> bytes:
        return struct.pack(f"<{len(values)}f", *values)

    @property
    def values(self) -> list[float]:
        return list(struct.unpack(f"<{self.dimensions}f", bytes(self.vector)))

    @staticmethod
    def crop_digest_of(image_path: str | None, outline: Any) -> str:
        """The SHA-256 of what a glyph's crop is cut from: its page's image file and its outline.

        Migration `vision 0002` repeats this to stamp the vectors made before it.
        """
        source = json.dumps({"image": image_path or "", "outline": outline}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(source.encode()).hexdigest()

    @classmethod
    def crop_digest_for(cls, graph: Graph) -> str:
        """The digest of the crop `graph` would give now. Reads `graph.item_image`."""
        return cls.crop_digest_of(graph.item_image.image.name, graph.annotation)


class HandSimilarity(models.Model):
    """One of the hands whose letters are most like a hand's (AI programme W1.3).

    Written only by `apps.vision.services.hand_similarity`, which compares
    every pair of hands letter by letter and keeps each hand's nearest. A hand
    has a row for each of its nearest, ranked from 1; the pair is stored from
    both sides, since each side has its own nearest.

    `letters` says what the similarity is made of: for each allograph both
    hands wrote, how alike their forms of it are and how many of each were
    compared, most compared first. A palaeographer can check those letters
    against each other instead of trusting one number.
    """

    hand = models.ForeignKey("scribes.Hand", on_delete=models.CASCADE, related_name="+")
    other = models.ForeignKey("scribes.Hand", on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()
    similarity = models.FloatField()
    # [{"allograph": id, "similarity": cosine, "glyphs": [this hand's, the other's]}]
    letters = models.JSONField()
    # The vectors compared, as "encoder@model_version".
    vectors = models.CharField(max_length=160)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["hand_id", "rank"]
        constraints = [
            models.UniqueConstraint(fields=["hand", "other"], name="hand_similarity_one_per_pair"),
            models.UniqueConstraint(fields=["hand", "rank"], name="hand_similarity_one_per_rank"),
            models.CheckConstraint(condition=~models.Q(hand=models.F("other")), name="hand_similarity_not_itself"),
        ]

    def __str__(self) -> str:
        return f"Hand {self.hand_id} → {self.other_id} (#{self.rank})"


class PageDraft(models.Model):
    """A user's request that one page's transcription be drafted by a model (AI programme W1.4).

    Drafting is decided page by page: the untranscribed tail is not drafted in
    bulk, and each draft records who asked for it. Written only by
    `apps.vision.services.page_drafts`: queued in the request, then read and
    filed by a worker. What it files is an ordinary Draft transcription,
    marked machine-drafted in its TEI, which waits for review like any other.
    The database allows a page one draft in the making at a time.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        WORKING = "working", "Working"
        DRAFTED = "drafted", "Drafted"
        FAILED = "failed", "Failed"
        REFUSED = "refused", "Refused"

    # A draft in the making. The constraint below names the same two.
    ACTIVE: ClassVar[tuple[str, ...]] = ("queued", "working")

    item_image = models.ForeignKey("manuscripts.ItemImage", on_delete=models.CASCADE, related_name="+")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    # Why it stopped, in words fit for the user; the cause is logged.
    error = models.TextField(blank=True, default="")
    ml_job = models.ForeignKey("ml.MLJob", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # The transcription it filed, while that exists.
    image_text = models.ForeignKey(
        "manuscripts.ImageText", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The draft's TEI as filed, before anyone edits it: what a reviewer's
    # corrections are measured against.
    drafted_content = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["item_image"],
                condition=models.Q(status__in=["queued", "working"]),
                name="page_draft_one_at_a_time",
            ),
        ]

    def __str__(self) -> str:
        return f"Draft of image {self.item_image_id} ({self.status})"
