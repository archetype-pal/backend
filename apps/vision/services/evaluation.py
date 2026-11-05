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

**The legacy as an encoder (C3).** DigiPal compared letters by what annotators
said of them: the components marked on a glyph and the features of each.
`descriptions` scores that the same way, so the search can be measured against
it before it replaces anything. A glyph's vector has a 1 for each component it
was described with and for each (component, feature) pair, scaled to unit
length, so the cosine between two glyphs is how much their descriptions overlap
(Ochiai's coefficient). Only described glyphs have one.

**Measured** on release local-2026-11-04, on the described glyphs that every
encoder has a vector for. Held out by charter (130 glyphs, neighbours from
958), descriptions put the right allograph nearest for 66.9% and had a
precision@10 of 68.0%; the search's vector (`glyph_search.PARTS`,
`10*trocr+ink+3*hog`) 89.2% and 67.6%. Held out by repository (548, from 540):
57.1% and 48.9%, against 62.2% and 43.5%. So the search finds the nearest
letter better and ranks ten no better. Many glyphs are described alike (2,851
of them by 10 components), so a glyph's nearest is any one of a group and its
ten nearest are the group. Fused, the two did far better than either: 93.1%
and 86.1% by charter, 76.5% and 56.8% by repository. A description is written
knowing the letter, so it is not blind to the label it is scored by: a glyph's
components alone point to its allograph for 63% of described glyphs.

Hands compared by descriptions, letter by letter as `hand_similarity` compares
them (a one-off run, not a command), dated charters as well as the vectors do.
Of the 39 hands that both they and `hog` compare, dated as `hand_dating` dates
them, descriptions were off by 23.9 years on other charters and 23.8 from
other repositories; `hog` by 26.2 and 35.4, `trocr` by 24.7 and 36.5. None of
Scribe Ab's charters has enough described glyphs to be compared. So for
comparing scripts the vectors do not beat the descriptions, and nothing of
DigiPal's is replaced: the search by components and features stays beside the
search by form.
"""

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from apps.annotations.models import Graph, GraphComponent
from apps.ml.evaluation import Metrics, Release, majority_baseline, score, stratified_baseline

from ..models import GlyphEmbedding

LABEL = "allograph"
# The encoder name under which the harness scores DigiPal's descriptions.
DESCRIPTIONS = "descriptions"
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


def description_vectors() -> Vectors:
    """Each described glyph's components and their features, as a unit vector over every term used.

    Described as `Graph.is_described` means it: an image glyph with a feature
    on at least one of its components.
    """
    terms: dict[int, set[tuple[int, int | None]]] = defaultdict(set)
    featured: set[int] = set()
    for graph_id, component_id, feature_id in GraphComponent.objects.filter(
        graph__annotation_type=Graph.AnnotationType.IMAGE, graph__deleted_at__isnull=True
    ).values_list("graph_id", "component_id", "features__id"):
        terms[graph_id].add((component_id, None))
        if feature_id is not None:
            terms[graph_id].add((component_id, feature_id))
            featured.add(graph_id)
    if not featured:
        raise EncoderEvaluationError("No glyph is described: no feature is recorded on any image glyph.")
    graphs = sorted(featured)
    # Which column holds which term changes no cosine.
    column = {term: position for position, term in enumerate({term for g in graphs for term in terms[g]})}
    matrix = np.zeros((len(graphs), len(column)), dtype=np.float32)
    for row, graph_id in enumerate(graphs):
        for term in terms[graph_id]:
            matrix[row, column[term]] = 1.0
    return Vectors(
        encoder=DESCRIPTIONS,
        model_name="digipal-descriptions",
        model_version="components-features-1",
        index={graph_id: row for row, graph_id in enumerate(graphs)},
        matrix=matrix / np.linalg.norm(matrix, axis=1, keepdims=True),
    )


def load_vectors(encoder: str) -> Vectors:
    """Every stored vector from `encoder`, refusing a mix of weights; or, as `descriptions`, DigiPal's.

    Vectors from two revisions do not share a space, and a neighbour found
    across them means nothing.
    """
    if encoder == DESCRIPTIONS:
        return description_vectors()
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


def fuse(parts: list[Vectors], weights: dict[str, float] | None = None) -> Vectors:
    """Several encoders as one: a glyph's similarity to another is the mean of theirs.

    Each part's unit vectors are scaled by sqrt(w / total weight) and set end to
    end, so the dot product of two fused vectors is the weighted mean of the
    parts' cosines. A part not named in `weights` weighs 1. Only glyphs that
    every part has a vector for are kept. A part that weighs other than 1 is
    named with its weight, e.g. `2*trocr+ink+hog`, so a recorded run says how
    it was made.
    """
    if len(parts) < 2:
        raise EncoderEvaluationError("Fusing takes at least two encoders.")
    weights = weights or {}
    unknown = set(weights) - {part.encoder for part in parts}
    if unknown:
        raise EncoderEvaluationError(f"Weights for encoders not being fused: {', '.join(sorted(unknown))}.")
    if any(weight <= 0 for weight in weights.values()):
        raise EncoderEvaluationError("A weight must be greater than 0.")
    shared = sorted(set.intersection(*(set(part.index) for part in parts)))
    if not shared:
        raise EncoderEvaluationError("No glyph has a vector from every encoder named.")
    each = [weights.get(part.encoder, 1.0) for part in parts]
    total = sum(each)

    def named(name: str, weight: float) -> str:
        return name if weight == 1 else f"{weight:g}*{name}"

    return Vectors(
        encoder="+".join(named(part.encoder, weight) for part, weight in zip(parts, each, strict=True)),
        model_name="+".join(named(part.model_name, weight) for part, weight in zip(parts, each, strict=True)),
        model_version="+".join(part.model_version for part in parts),
        index={graph_id: position for position, graph_id in enumerate(shared)},
        matrix=np.hstack(
            [
                part.matrix[[part.index[graph_id] for graph_id in shared]] * math.sqrt(weight / total)
                for part, weight in zip(parts, each, strict=True)
            ]
        ),
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
