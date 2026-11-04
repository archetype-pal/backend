import hashlib
import json
import struct
from typing import TYPE_CHECKING, Any, ClassVar

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
