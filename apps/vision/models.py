import struct
from typing import ClassVar

from django.db import models
from django.db.models.functions import Length


class GlyphEmbedding(models.Model):
    """One glyph's vector from one self-hosted encoder (AI programme W1.2).

    Written only by `apps.vision.services.embedding`, from what an encoder
    returned through the ledger; `ml_job` is the row that made it. A glyph has
    at most one vector per encoder, so two encoders can be compared side by
    side over the same glyphs.

    The vector is stored as little-endian float32 bytes, which is how every
    reader (a nearest-neighbour search, a search index) wants it. The database
    refuses a vector whose length does not match `dimensions`.
    """

    graph = models.ForeignKey("annotations.Graph", on_delete=models.CASCADE, related_name="embeddings")
    # The provider that made it, e.g. "dinov2". `model_name` and
    # `model_version` say which weights, as the encoder reported them.
    encoder = models.CharField(max_length=32)
    model_name = models.CharField(max_length=128)
    model_version = models.CharField(max_length=128)
    dimensions = models.PositiveSmallIntegerField()
    vector = models.BinaryField()
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
