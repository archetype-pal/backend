"""Hands whose letters are alike (AI programme W1.3).

Two hands are compared letter by letter, never on their mix of letters. For
each allograph both wrote, each hand's forms of it are averaged into one
vector, and the two averages are compared by their cosine. The hands'
similarity is the mean of those cosines, each weighted by the fewer of the
two hands' forms of that letter, over at least `MIN_SHARED` letters.

Before averaging, each glyph's vector has its allograph's mean over the whole
corpus taken away. What is left is how the glyph departs from the usual form
of its letter, which is what sets one hand apart from another.

The vectors are `hog`'s, histograms of the directions a letter's strokes run
in. `eval_hand_similarity` measured them on the one scribe the database
attributes to more than one charter, Barrow's Scribe Ab, on the dev database
of 2026-11-05, where five of the scribe's charters have vectors. Asked for its
ten nearest hands, each of those charters found on average almost two of the
other four: 9 of 20, against 1.8 by chance. Each had another of them within its
first four. `trocr`'s vectors found 7 and `ink`'s 4, and `hog` runs in-process,
with no model to host. Five charters are a thin test: run the harness again
as scribes are attributed.

A glyph's vector counts only while it is current: one made from a crop the
glyph no longer has (`GlyphEmbedding.crop_digest`) is left out.
"""

from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import groupby
from typing import Any

from django.db import transaction
import numpy as np

from apps.annotations.models import Graph

from ..models import GlyphEmbedding, HandSimilarity
from .glyph_search import Part

PART = Part("hog", "48px-6cell-9bin-1", 1764)
# A hand with fewer current glyphs than this is not compared: too few letters
# to say how it writes them.
MIN_GLYPHS = 10
# Two hands sharing fewer letters than this are not compared.
MIN_SHARED = 3
# The nearest hands kept for each hand.
NEAREST = 20


@dataclass
class _Letter:
    """One allograph's part in the comparison."""

    allograph_id: int
    positions: dict[int, int]  # hand index → row of `cosines`
    counts: np.ndarray  # glyphs each of those hands wrote of it
    cosines: np.ndarray  # between the hands' centred means


@dataclass
class Comparison:
    """Every compared hand against every other."""

    vectors: str
    hands: list[int]
    glyphs: dict[int, int]  # every hand with a current glyph → how many
    similarity: np.ndarray  # hands × hands; -inf where two hands cannot be compared
    letters: list[_Letter] = field(default_factory=list)

    def nearest(self, hand_index: int, count: int = NEAREST) -> list[int]:
        """The indices of the hands most like this one, most alike first."""
        row = self.similarity[hand_index]
        order = np.argsort(-row, kind="stable")
        return [int(j) for j in order if np.isfinite(row[j])][:count]

    def letters_between(self, i: int, j: int) -> list[dict[str, Any]]:
        """What the similarity of hands `i` and `j` is made of, most compared letter first."""
        shared = []
        for letter in self.letters:
            if i in letter.positions and j in letter.positions:
                a, b = letter.positions[i], letter.positions[j]
                glyphs = [int(letter.counts[a]), int(letter.counts[b])]
                shared.append(
                    {
                        "allograph": letter.allograph_id,
                        "similarity": round(float(letter.cosines[a, b]), 4),
                        "glyphs": glyphs,
                    }
                )
        return sorted(shared, key=lambda entry: (-min(entry["glyphs"]), -entry["similarity"]))


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def _vectors(part: Part):
    return GlyphEmbedding.objects.filter(
        encoder=part.encoder,
        model_version=part.model_version,
        dimensions=part.dimensions,
        graph__annotation_type=Graph.AnnotationType.IMAGE,
        graph__deleted_at__isnull=True,
    )


def current_glyphs(part: Part | None = None) -> dict[int, int]:
    """Each glyph with a current vector from `part` (default `PART`), and its hand."""
    rows = _vectors(part or PART).values_list(
        "graph_id", "graph__hand_id", "crop_digest", "graph__item_image__image", "graph__annotation"
    )
    return {
        graph_id: hand_id
        for graph_id, hand_id, digest, image_path, outline in rows.iterator(chunk_size=2000)
        if digest == GlyphEmbedding.crop_digest_of(image_path, outline)
    }


def _by_allograph(part: Part, current: dict[int, int]) -> Iterator[tuple[int, list[tuple[int, np.ndarray]]]]:
    """Each allograph's current glyphs as (hand, unit vector), one allograph in memory at a time."""
    rows = (
        _vectors(part)
        .order_by("graph__allograph_id", "graph_id")
        .values_list("graph_id", "graph__allograph_id", "vector")
        .iterator(chunk_size=2000)
    )
    for allograph_id, group in groupby((row for row in rows if row[0] in current), key=lambda row: row[1]):
        yield (
            allograph_id,
            [
                (current[graph_id], np.frombuffer(bytes(vector), dtype="<f4").astype(np.float64))
                for graph_id, _, vector in group
            ],
        )


def compare(part: Part | None = None) -> Comparison:
    """Compare every hand with enough current glyphs against every other, by `part` (default `PART`)."""
    part = part or PART
    current = current_glyphs(part)
    glyphs = Counter(current.values())
    hands = sorted(hand for hand, count in glyphs.items() if count >= MIN_GLYPHS)
    position = {hand: index for index, hand in enumerate(hands)}
    total = np.zeros((len(hands), len(hands)))
    weight = np.zeros((len(hands), len(hands)))
    shared = np.zeros((len(hands), len(hands)), dtype=int)
    letters = []

    for allograph_id, rows in _by_allograph(part, current):
        matrix = _unit(np.stack([vector for _, vector in rows]))
        # The allograph's usual form, over every hand that wrote it, compared or not.
        centred = matrix - matrix.mean(axis=0)
        by_hand: dict[int, list[np.ndarray]] = defaultdict(list)
        for (hand, _), vector in zip(rows, centred, strict=True):
            if hand in position:
                by_hand[hand].append(vector)
        if len(by_hand) < 2:
            continue
        indices = np.array([position[hand] for hand in sorted(by_hand)])
        counts = np.array([len(by_hand[hand]) for hand in sorted(by_hand)])
        means = _unit(np.stack([np.mean(by_hand[hand], axis=0) for hand in sorted(by_hand)]))
        cosines = means @ means.T
        weights = np.minimum.outer(counts, counts).astype(float)
        block = np.ix_(indices, indices)
        total[block] += weights * cosines
        weight[block] += weights
        shared[block] += 1
        letters.append(
            _Letter(
                allograph_id=allograph_id,
                positions={int(index): row for row, index in enumerate(indices)},
                counts=counts,
                cosines=cosines.astype(np.float32),
            )
        )

    with np.errstate(invalid="ignore", divide="ignore"):
        similarity = np.where(shared >= MIN_SHARED, total / weight, -np.inf)
    np.fill_diagonal(similarity, -np.inf)
    return Comparison(
        vectors=f"{part.encoder}@{part.model_version}",
        hands=hands,
        glyphs=dict(glyphs),
        similarity=similarity,
        letters=letters,
    )


@dataclass
class Tally:
    compared: int
    too_few_glyphs: int
    stored: int


def compare_hands(part: Part | None = None, nearest: int = NEAREST) -> Tally:
    """Compare the hands and replace every hand's stored nearest with the new ones."""
    comparison = compare(part)
    rows = [
        HandSimilarity(
            hand_id=hand_id,
            other_id=comparison.hands[j],
            rank=rank,
            similarity=round(float(comparison.similarity[i, j]), 4),
            letters=comparison.letters_between(i, j),
            vectors=comparison.vectors,
        )
        for i, hand_id in enumerate(comparison.hands)
        for rank, j in enumerate(comparison.nearest(i, nearest), start=1)
    ]
    with transaction.atomic():
        HandSimilarity.objects.all().delete()
        HandSimilarity.objects.bulk_create(rows, batch_size=1000)
    return Tally(
        compared=len(comparison.hands),
        too_few_glyphs=len(comparison.glyphs) - len(comparison.hands),
        stored=len(rows),
    )


# How far down a hand's nearest the harness looks for the same scribe's other hands.
SCORED_AT = 10


@dataclass
class AttributionScore:
    """How well a comparison finds the hands one scribe wrote, beside chance."""

    scribes: int
    hands: int
    found: int  # fellow hands within each hand's `SCORED_AT` nearest, summed
    possible: int  # fellow hands, summed over every hand asked
    by_chance: float
    best_ranks: list[int]  # per hand asked, where its nearest fellow ranks
    percentile: float  # mean over every fellow; 0.5 is chance


def score_attributions(comparison: Comparison, at: int = SCORED_AT) -> AttributionScore | None:
    """Ask each attributed hand for its nearest, and count its scribe's other hands among them.

    The database's attributions are the only ground truth there is for which
    charters one scribe wrote. A scribe below pk 1 is the DigiPal import's
    placeholder for an unattributed hand, not a scribe. Only scribes with two
    or more compared hands can be scored; None if there is none.
    """
    from apps.scribes.models import Hand

    scribe_of = dict(Hand.objects.filter(pk__in=comparison.hands, scribe_id__gte=1).values_list("pk", "scribe_id"))
    groups: dict[int, list[int]] = defaultdict(list)
    for index, hand in enumerate(comparison.hands):
        if hand in scribe_of:
            groups[scribe_of[hand]].append(index)
    groups = {scribe: indices for scribe, indices in groups.items() if len(indices) >= 2}
    if not groups:
        return None

    candidates = len(comparison.hands) - 1
    found = possible = 0
    best_ranks, percentiles = [], []
    for indices in groups.values():
        for i in indices:
            order = comparison.nearest(i, count=candidates)
            # A hand that shares too few letters to be compared ranks last.
            ranks = [order.index(j) + 1 if j in order else candidates for j in indices if j != i]
            found += sum(1 for rank in ranks if rank <= at)
            possible += len(ranks)
            best_ranks.append(min(ranks))
            percentiles += [1 - (rank - 1) / max(candidates - 1, 1) for rank in ranks]
    return AttributionScore(
        scribes=len(groups),
        hands=sum(len(indices) for indices in groups.values()),
        found=found,
        possible=possible,
        by_chance=possible * min(at, candidates) / candidates,
        best_ranks=best_ranks,
        percentile=float(np.mean(percentiles)),
    )


def part_for(encoder: str) -> Part:
    """The stored vectors of `encoder`, as a part; refuses a mix of weights."""
    found = set(GlyphEmbedding.objects.filter(encoder=encoder).values_list("model_version", "dimensions").distinct())
    if len(found) != 1:
        raise ValueError(
            f"'{encoder}' has no stored vectors."
            if not found
            else f"'{encoder}' vectors come from {len(found)} different weights; re-embed with --force first."
        )
    model_version, dimensions = found.pop()
    return Part(encoder, model_version, dimensions)


@dataclass
class NearestHands:
    """A hand's stored nearest, and what a reader needs to make sense of none."""

    hand_id: int
    glyphs: int  # its glyphs with a current vector
    rows: list[HandSimilarity]
    allographs: dict[int, Any]  # the allographs its letters name


def nearest_hands(hand_id: int) -> NearestHands:
    """The hands stored as most like `hand_id`'s, most alike first. Raises `Hand.DoesNotExist`."""
    from apps.scribes.models import Hand
    from apps.symbols_structure.models import Allograph

    if not Hand.objects.filter(pk=hand_id).exists():
        raise Hand.DoesNotExist(f"No hand {hand_id}.")
    rows = list(
        HandSimilarity.objects.filter(hand_id=hand_id)
        .select_related(
            "other__scribe",
            "other__date",
            "other__place",
            "other__item_part__current_item__repository",
            "other__item_part__historical_item",
        )
        .prefetch_related("other__item_part__historical_item__catalogue_numbers__catalogue")
        .order_by("rank")
    )
    allograph_ids = {entry["allograph"] for row in rows for entry in row.letters}
    glyphs = (
        _vectors(PART)
        .filter(graph__hand_id=hand_id)
        .values_list("crop_digest", "graph__item_image__image", "graph__annotation")
    )
    return NearestHands(
        hand_id=hand_id,
        glyphs=sum(
            1 for digest, image_path, outline in glyphs if digest == GlyphEmbedding.crop_digest_of(image_path, outline)
        ),
        rows=rows,
        allographs=Allograph.objects.select_related("character").in_bulk(allograph_ids),
    )


# The stored relations a hand summary reads, so a list of hands costs a fixed number of queries.
_SUMMARY_RELATIONS = (
    "scribe",
    "date",
    "place",
    "item_part__current_item__repository",
    "item_part__historical_item",
)
_SUMMARY_PREFETCH = "item_part__historical_item__catalogue_numbers__catalogue"


@dataclass
class ScribeMatch:
    """A hand not attributed to the scribe, and which of the scribe's hands it is near."""

    other: Any  # the Hand
    near: list[HandSimilarity]  # rows from the scribe's hands to it, nearest rank first

    @property
    def best(self) -> float:
        return float(max(row.similarity for row in self.near))


@dataclass
class ScribeNearest:
    """The hands most like a scribe's, and how near the scribe's own hands come to each other."""

    scribe_id: int
    hands: list[Any]  # the scribe's hands
    rows: dict[int, list[HandSimilarity]]  # per hand of the scribe, its stored nearest
    matches: list[ScribeMatch]


def nearest_to_scribe(scribe_id: int, limit: int = NEAREST) -> ScribeNearest:
    """The hands stored as near this scribe's hands, those near most of them first.

    A hand is a match when it is among the stored nearest of at least one of the
    scribe's hands and is not itself attributed to the scribe. Matches near more
    of the scribe's hands come first, then the more alike. Each hand's stored
    nearest are kept too, so a reader can see whether the scribe's own hands
    find each other at all: the measure of how far to trust the matches.

    Raises `Scribe.DoesNotExist` for no scribe, or for the DigiPal import's
    placeholder below pk 1, which stands for no attribution.
    """
    from apps.scribes.models import Hand, Scribe

    if scribe_id < 1 or not Scribe.objects.filter(pk=scribe_id).exists():
        raise Scribe.DoesNotExist(f"No scribe {scribe_id}.")
    hands = list(
        Hand.objects.filter(scribe_id=scribe_id)
        .select_related(*_SUMMARY_RELATIONS)
        .prefetch_related(_SUMMARY_PREFETCH)
        .order_by("pk")
    )
    own = {hand.pk for hand in hands}
    rows: dict[int, list[HandSimilarity]] = defaultdict(list)
    for row in (
        HandSimilarity.objects.filter(hand_id__in=own)
        .select_related(*(f"other__{relation}" for relation in _SUMMARY_RELATIONS))
        .prefetch_related(f"other__{_SUMMARY_PREFETCH}")
        .order_by("hand_id", "rank")
    ):
        rows[row.hand_id].append(row)

    near: dict[int, list[HandSimilarity]] = defaultdict(list)
    for hand_rows in rows.values():
        for row in hand_rows:
            if row.other_id not in own:
                near[row.other_id].append(row)
    matches = [
        ScribeMatch(other=found[0].other, near=sorted(found, key=lambda row: (row.rank, row.hand_id)))
        for found in near.values()
    ]
    matches.sort(key=lambda match: (-len(match.near), -match.best, match.other.pk))
    return ScribeNearest(scribe_id=scribe_id, hands=hands, rows=dict(rows), matches=matches[:limit])
