"""The vector a glyph is searched by, for "letters like this" (AI programme W1.2).

The harness (`eval_glyph_encoder`) measured which encoders find the same
letter-form in another charter, and how much each should weigh. This module
writes that choice down, once. The search index stores each glyph's vector,
fused from `PARTS` exactly as `eval_glyph_encoder --fuse --weight` fused them
when it scored them.

Each part is pinned to the weights that made its vectors (`model_version`).
A glyph with no search vector is one that is missing a part, or that holds a
part made by other weights. Vectors from two revisions do not share a space,
so neighbours found across them would mean nothing.
"""

from dataclasses import dataclass
import math

from django.db.models import Prefetch
from django.dispatch import Signal
import numpy as np

from apps.annotations.models import Graph

from ..models import GlyphEmbedding


@dataclass(frozen=True)
class Part:
    encoder: str
    model_version: str
    dimensions: int
    weight: float = 1.0


# The TrOCR encoder trained on medieval Latin, and the two shape descriptors.
# The weights were chosen by five-fold cross-validation, by charter, within the
# training charters of release local-2026-11-04's by-charter split: 10 : 1 : 3
# had the best nearest-neighbour allograph accuracy on a grid of trocr 0.5 to
# 32 and hog 1 to 6, on a surface flat to within a point around it. Only then
# was it scored on the held-out charters (`eval_glyph_encoder --fuse
# --weight trocr=10 --weight hog=3`: 0.720, against 0.637 for trocr alone).
PARTS = (
    Part("trocr", "08e146d2dbf4673da24ce2f2dc5f3343bc62099c", 768, weight=10.0),
    Part("ink", "otsu-32-1", 1024),
    Part("hog", "48px-6cell-9bin-1", 1764, weight=3.0),
)
DIMENSIONS = sum(part.dimensions for part in PARTS)
ENCODERS = tuple(part.encoder for part in PARTS)

# Sent with `graph_ids` once new vectors from a part's encoder are stored, so
# whoever keeps a copy of the search vector (the search index) can rebuild it.
search_vectors_changed = Signal()

_PREFETCHED = "_search_embeddings"


def prefetch() -> Prefetch:
    """What a queryset of graphs prefetches, so `search_vector` reads nothing more."""
    return Prefetch(
        "embeddings",
        queryset=GlyphEmbedding.objects.filter(encoder__in=ENCODERS).only(
            "graph_id", "encoder", "model_version", "dimensions", "vector"
        ),
        to_attr=_PREFETCHED,
    )


def search_vector(graph: Graph) -> list[float] | None:
    """The glyph's fused vector, or None if it has no vector from one of `PARTS`' weights.

    Each part is scaled to unit length, then by sqrt(weight / total weight),
    so the dot product of two search vectors is the weighted mean of their
    parts' cosines: the similarity the harness scored.
    """
    rows = getattr(graph, _PREFETCHED, None)
    if rows is None:
        rows = list(graph.embeddings.filter(encoder__in=ENCODERS))
    by_encoder = {row.encoder: row for row in rows}
    total = sum(part.weight for part in PARTS)
    pieces = []
    for part in PARTS:
        row = by_encoder.get(part.encoder)
        if row is None or row.model_version != part.model_version or row.dimensions != part.dimensions:
            return None
        vector = np.frombuffer(bytes(row.vector), dtype="<f4").astype(np.float64)
        norm = float(np.linalg.norm(vector))
        pieces.append((vector / norm if norm else vector) * math.sqrt(part.weight / total))
    fused = np.concatenate(pieces)
    # A blank crop gives a zero vector, and a zero vector has no direction to search by.
    if not fused.any():
        return None
    return [round(float(value), 6) for value in fused]
