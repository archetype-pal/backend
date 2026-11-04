"""Scoring a glyph encoder by its nearest neighbours (W1.2, through W0.3).

An encoder is measured the way the harness measures everything: on a frozen
release, by one of its splits, beside baselines scored on the same glyphs. No
glyph from a held-out charter is ever a neighbour, because the split is by
charter.

Each held-out glyph is given the allograph of its nearest training glyph (or,
for k > 1, the allograph its k nearest carry the most similarity for). That
prediction goes through the harness's `score`, so the number is the same kind
of number every other model on the programme reports.

Two more numbers come with it. **Precision@10** is the share of a glyph's ten
nearest training glyphs that are the same allograph: the number a search for
"letters that look like this" stands or falls by. **Character accuracy** says
how much of the allograph error is between forms of one letter, which an
off-the-shelf encoder has no reason to separate.

Only glyphs that have a vector can be scored. Locally, many pages have no image
file, so coverage is reported beside every score, and the baselines are scored
on exactly the glyphs the encoder was.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np

from apps.ml.evaluation import Metrics, Release, majority_baseline, score, stratified_baseline

from ..models import GlyphEmbedding

LABEL = "allograph"
PRECISION_AT = 10
# Rows of the similarity matrix computed at once; bounds memory, not the result.
CHUNK = 1024


class EncoderEvaluationError(Exception):
    """The encoder cannot be scored on this release as asked."""


@dataclass(frozen=True)
class Vectors:
    """One encoder's vectors, unit length, indexed by glyph."""

    encoder: str
    model_name: str
    model_version: str
    index: dict[int, int]
    matrix: np.ndarray


@dataclass(frozen=True)
class EncoderScore:
    encoder: str
    model_name: str
    model_version: str
    k: int
    train_total: int
    train_scored: int
    held_total: int
    held_scored: int
    metrics: Metrics
    character_accuracy: float
    precision_at_10: float
    majority: Metrics
    stratified: Metrics

    def notes(self, split: str) -> str:
        return (
            f"{self.k}-nearest-neighbour {LABEL} over the {split} train split's {self.encoder} vectors (cosine). "
            f"Scored on {self.held_scored} of {self.held_total} held-out glyphs, those with a vector; "
            f"neighbours drawn from {self.train_scored} of {self.train_total} training glyphs. "
            f"Character accuracy {self.character_accuracy:.4f}; precision@{PRECISION_AT} "
            f"{self.precision_at_10:.4f}. Baselines scored on the same glyphs."
        )


def load_vectors(encoder: str) -> Vectors:
    """Every stored vector from `encoder`, refusing a mix of weights.

    Vectors from two revisions do not share a space, and a neighbour found
    across them means nothing.
    """
    rows = list(
        GlyphEmbedding.objects.filter(encoder=encoder)
        .order_by("graph_id")
        .values_list("graph_id", "model_name", "model_version", "dimensions", "vector")
    )
    if not rows:
        raise EncoderEvaluationError(f"No glyph has a vector from '{encoder}'. Run embed_glyphs first.")
    weights = {(name, version, dimensions) for _, name, version, dimensions, _ in rows}
    if len(weights) > 1:
        raise EncoderEvaluationError(
            f"'{encoder}' vectors come from {len(weights)} different weights; re-embed with --force first."
        )
    (model_name, model_version, dimensions) = weights.pop()
    matrix = np.frombuffer(b"".join(bytes(row[4]) for row in rows), dtype="<f4").reshape(len(rows), dimensions)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.where(norms == 0, 1, norms)
    return Vectors(
        encoder=encoder,
        model_name=model_name,
        model_version=model_version,
        index={row[0]: position for position, row in enumerate(rows)},
        matrix=matrix,
    )


def nearest(train: np.ndarray, queries: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """For each query, the positions of its `k` most similar training rows, nearest first, and their similarities."""
    k = min(k, len(train))
    positions = np.empty((len(queries), k), dtype=np.int64)
    similarities = np.empty((len(queries), k), dtype=np.float32)
    for start in range(0, len(queries), CHUNK):
        block = queries[start : start + CHUNK] @ train.T
        # A stable sort breaks ties by training position, so a run is
        # reproducible. A blank crop's zero vector ties with every glyph.
        top = np.argsort(-block, axis=1, kind="stable")[:, :k]
        positions[start : start + CHUNK] = top
        similarities[start : start + CHUNK] = np.take_along_axis(block, top, axis=1)
    return positions, similarities


def vote(labels: list[str], similarities: list[float]) -> str:
    """The label its neighbours carry the most similarity for; the nearest's label on a tie."""
    weight: dict[str, float] = defaultdict(float)
    for label, similarity in zip(labels, similarities, strict=True):
        weight[label] += similarity
    best = max(weight.values())
    return next(label for label in labels if weight[label] == best)


def score_encoder(
    release: Release,
    vectors: Vectors,
    *,
    split: str = "by_charter",
    k: int = 1,
    only: set[int] | None = None,
) -> EncoderScore:
    """Score `vectors` on `release`'s `split`. `only` restricts it to those glyphs, to compare encoders fairly."""
    if k < 1:
        raise EncoderEvaluationError("k must be at least 1.")
    train_rows, held_rows = release.partition(split)
    train_rows = [row for row in train_rows if row.get(LABEL)]
    held_rows = [row for row in held_rows if row.get(LABEL)]

    def scored(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if row["graph_id"] in vectors.index and (only is None or row["graph_id"] in only)]

    train, held = scored(train_rows), scored(held_rows)
    if not train or not held:
        raise EncoderEvaluationError(
            f"Nothing to score: {len(train)} training and {len(held)} held-out glyphs "
            f"have a '{vectors.encoder}' vector."
        )

    train_matrix = vectors.matrix[[vectors.index[row["graph_id"]] for row in train]]
    held_matrix = vectors.matrix[[vectors.index[row["graph_id"]] for row in held]]
    positions, similarities = nearest(train_matrix, held_matrix, max(k, PRECISION_AT))

    truth = [row[LABEL] for row in held]
    predicted, characters, hits = [], [], []
    for row, near, sims in zip(held, positions, similarities, strict=True):
        neighbours = [train[position] for position in near]
        predicted.append(vote([n[LABEL] for n in neighbours[:k]], [float(s) for s in sims[:k]]))
        characters.append(vote([n["character"] for n in neighbours[:k]], [float(s) for s in sims[:k]]))
        top = neighbours[:PRECISION_AT]
        hits.append(sum(1 for n in top if n[LABEL] == row[LABEL]) / len(top))

    train_labels = [row[LABEL] for row in train]
    character_truth = [row["character"] for row in held]
    return EncoderScore(
        encoder=vectors.encoder,
        model_name=vectors.model_name,
        model_version=vectors.model_version,
        k=k,
        train_total=len(train_rows),
        train_scored=len(train),
        held_total=len(held_rows),
        held_scored=len(held),
        metrics=score(truth, predicted),
        character_accuracy=sum(1 for t, p in zip(character_truth, characters, strict=True) if t == p) / len(held),
        precision_at_10=sum(hits) / len(hits),
        majority=score(truth, majority_baseline(train_labels, len(truth))),
        stratified=score(truth, stratified_baseline(train_labels, len(truth), seed=release.version)),
    )
