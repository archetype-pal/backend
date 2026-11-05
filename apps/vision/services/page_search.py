"""Conversational annotation (AI programme W3.4): "label every long-s on this folio".

An annotator who has marked a few examples of a letter on a page asks for the
rest. The request is read against the letters already marked on that page; the
page is searched for windows shaped like those examples (`hog-page`, in this
process); and what it finds goes to W0.5's review queue as proposals, one
ledger job per request. Nothing is annotated until a person accepts it there.

**The request is read without a model.** It only has to name one of the
letters marked on the page, which a match against their names does, and a
request it cannot settle is answered with a question: which of these letters,
or that there are too few examples to search by. Nothing leaves the server.
"""

import base64
from dataclasses import dataclass, field
import io
import re
import statistics
from typing import Any

from django.db import transaction
from PIL import Image

from apps.annotations.models import Graph, GraphProposal
from apps.annotations.services import proposals
from apps.manuscripts.models import ItemImage
from apps.manuscripts.services.iiif import get_iiif_region_from_geojson
from apps.ml.models import MLJob
from apps.ml.providers.shape import HOG_SIDE
from apps.ml.services import InferenceService
from apps.scribes.models import Hand
from apps.symbols_structure.models import Allograph
from apps.vision import images

TASK = "W3.4"
PROVIDER = "hog-page"
# Fewer examples than this is too little to say what the letter looks like on this page.
MIN_EXAMPLES = 2
DEFAULT_COUNT = 20
MAX_COUNT = 100
# The longest side the page is rendered at for the search; smaller letters on a larger page are refused.
MAX_RENDITION = 6000

Box = tuple[float, float, float, float]  # x, y, w, h in the page's pixels, origin at the top left


class CannotSearch(ValueError):
    """The request cannot be answered with proposals; `reason` says why, for the reply."""

    def __init__(self, reason: str, **details: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details


def _box(annotation: Any, height: int) -> Box | None:
    region = get_iiif_region_from_geojson(annotation, image_height=height)
    if region in ("", "full"):
        return None
    x, y, w, h = (float(value) for value in region.split(","))
    return x, y, w, h


def typical(boxes: list[Box]) -> list[Box]:
    """The boxes whose longer side is within half to twice the median's.

    Some glyph rows mark a whole line or block of text under a letter's name; a
    box like that says nothing about the letter's shape.
    """
    if not boxes:
        return []
    middle = statistics.median(max(w, h) for _, _, w, h in boxes)
    return [box for box in boxes if 0.5 * middle <= max(box[2], box[3]) <= 2 * middle]


@dataclass
class PageLetters:
    """The page's marked glyphs, grouped by letter, as boxes in its pixels."""

    image: ItemImage
    width: int
    height: int
    by_allograph: dict[int, list[tuple[Graph, Box]]] = field(default_factory=dict)
    marked: list[Box] = field(default_factory=list)  # every glyph and pending proposal on the page

    def examples(self, allograph_id: int, hand_id: int | None = None) -> list[tuple[Graph, Box]]:
        rows = [
            (graph, box)
            for graph, box in self.by_allograph.get(allograph_id, [])
            if hand_id is None or graph.hand_id == hand_id
        ]
        kept = set(typical([box for _, box in rows]))
        return [(graph, box) for graph, box in rows if box in kept]


def page_letters(image: ItemImage) -> PageLetters:
    """Raises `images.ImageUnavailable` when the page's height is unknown: a box without it is mirrored."""
    width, height = images.dimensions(image)
    letters = PageLetters(image=image, width=width, height=height)
    for graph in Graph.objects.filter(item_image=image, annotation_type=Graph.AnnotationType.IMAGE).only(
        "id", "annotation", "allograph_id", "hand_id"
    ):
        box = _box(graph.annotation, height)
        if box is None:
            continue
        letters.marked.append(box)
        if graph.allograph_id is not None:
            letters.by_allograph.setdefault(graph.allograph_id, []).append((graph, box))
    for annotation in GraphProposal.objects.filter(item_image=image, status=GraphProposal.Status.PENDING).values_list(
        "annotation", flat=True
    ):
        box = _box(annotation, height)
        if box is not None:
            letters.marked.append(box)
    return letters


_WORD = re.compile(r"[^\W_]+")


def _words(text: str, *, fold: bool = True) -> set[str]:
    return set(_WORD.findall(text.casefold() if fold else text))


def _names_character(name: str, exact: set[str], folded: set[str]) -> bool:
    """Whether the request names the character. A single letter's case matters: S and s are two characters."""
    if len(name) == 1:
        return name in exact
    character = _words(name)
    return bool(character) and character <= folded


def read_request(text: str, letters: PageLetters) -> list[Allograph]:
    """The letters marked on the page that `text` can mean, best reading first.

    A letter is meant when the request names its character and every word of
    its allograph's name ("long-s" is "s, long"). When none is named that
    fully, the letters whose character alone is named are offered instead
    ("every s" when the page has a long and a round one).
    """
    exact, folded = _words(text, fold=False), _words(text)
    on_page = Allograph.objects.filter(pk__in=letters.by_allograph).select_related("character")
    full: list[Allograph] = []
    partial: list[Allograph] = []
    for allograph in on_page:
        if not _names_character(allograph.character.name, exact, folded):
            continue
        (full if _words(allograph.name) <= folded else partial).append(allograph)
    order = lambda allograph: (-len(letters.by_allograph[allograph.pk]), allograph.pk)  # noqa: E731
    return sorted(full, key=order) if full else sorted(partial, key=order)


@dataclass
class Search:
    allograph: Allograph
    hand: Hand | None
    examples: int
    job: MLJob
    proposals: list[GraphProposal]


def find_on_page(
    letters: PageLetters,
    allograph: Allograph,
    *,
    hand: Hand | None = None,
    count: int = DEFAULT_COUNT,
    actor: Any | None = None,
) -> Search:
    """Search the page for more of `allograph` and queue what is found as proposals.

    Raises `CannotSearch` with `too_few_examples` or `page_too_large`, and
    `images.ImageUnavailable` when the page cannot be fetched. A refused or
    failed job is returned with no proposals: the ledger row says why.
    """
    examples = letters.examples(allograph.pk, hand.pk if hand else None)
    if len(examples) < MIN_EXAMPLES:
        raise CannotSearch("too_few_examples", examples=len(examples), minimum=MIN_EXAMPLES)
    if hand is None:
        hands = {graph.hand_id for graph, _ in examples}
        hand = Hand.objects.get(pk=hands.pop()) if len(hands) == 1 and None not in hands else None

    side = statistics.median(max(w, h) for _, (_, _, w, h) in examples)
    scale = HOG_SIDE / side
    if max(letters.width, letters.height) * scale > MAX_RENDITION:
        raise CannotSearch("page_too_large", side=round(side), maximum=MAX_RENDITION)
    page = images.rendition(letters.image, width=max(1, round(letters.width * scale)))
    # The image server rounds; measure the scale it gave rather than the one asked for.
    rendered_width = Image.open(io.BytesIO(page)).size[0]
    scale = rendered_width / letters.width

    def scaled(box: Box) -> list[float]:
        return [round(value * scale, 2) for value in box]

    inputs = {
        "page": base64.b64encode(page).decode("ascii"),
        "examples": [scaled(box) for _, box in examples],
        "marked": [scaled(box) for box in letters.marked],
        "count": count,
    }
    params = {
        "item_image": letters.image.pk,
        "allograph": allograph.pk,
        "hand": hand.pk if hand else None,
        "examples": [graph.pk for graph, _ in examples],
    }
    service = InferenceService()
    job = service.submit(task=TASK, provider=PROVIDER, inputs=inputs, params=params, actor=actor, dispatch=False)
    if job.status == MLJob.Status.PENDING:
        job = service.run(job.pk, inputs=inputs, params=params)
    if job.status != MLJob.Status.SUCCEEDED:
        return Search(allograph=allograph, hand=hand, examples=len(examples), job=job, proposals=[])

    made = []
    with transaction.atomic():
        for found in getattr(job, "_output", {}).get("boxes", []):
            box = {
                "x": found["x"] / scale / letters.width,
                "y": found["y"] / scale / letters.height,
                "w": found["w"] / scale / letters.width,
                "h": found["h"] / scale / letters.height,
            }
            made.append(
                proposals.propose(
                    item_image_id=letters.image.pk,
                    annotation=images.ring_from_box(box, width=letters.width, height=letters.height),
                    allograph_id=allograph.pk,
                    hand_id=hand.pk if hand else None,
                    annotation_type=str(Graph.AnnotationType.IMAGE),
                    confidence=found["score"],
                    ml_job_id=job.pk,
                )
            )
    return Search(allograph=allograph, hand=hand, examples=len(examples), job=job, proposals=made)
