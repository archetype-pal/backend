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

**What the search finds, measured.** `eval_page_search` hides all but three of
a page's examples of a letter and counts how many of the hidden ones are among
the proposals. On the dev database of 2026-11-05 (40 letters on 26 pages, 169
hidden examples), 37 were among as many proposals as were hidden and 69 among
three times as many, against 1.1 and 3.2 by chance. That is a lower bound,
since the pages are annotated in part: a proposal that is a true, unmarked
example of the letter counts against it. Looked at, the first proposals for a
common, distinctive form (long s) were nearly all long s, and f, its usual
confusion; for d the first few were, then round letters; for a rare capital,
few were. Asking for a letter with many examples on the page works best.
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
from apps.ml.providers.shape import HOG_CELL, HOG_SIDE
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
    # Rejected ones too: asking again must move on to the next candidates, not
    # bring back what a reviewer has just turned down. An accepted one is a graph above.
    for annotation in GraphProposal.objects.filter(
        item_image=image,
        status__in=[GraphProposal.Status.PENDING, GraphProposal.Status.REJECTED],
        # What someone asked about in the viewer says nothing about what a search should skip.
        requested_by__isnull=True,
    ).values_list("annotation", flat=True):
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


@dataclass
class Evaluation:
    """How many hidden examples of a letter the search finds again, page by page."""

    letters: int  # (page, hand, letter) searched
    pages: int
    shown: int  # examples shown per letter
    hidden: int
    within_hidden: int  # found among as many proposals as were hidden
    within_thrice: int  # found among three times as many
    unavailable_pages: int
    # The hidden examples as many, and three times as many, proposals would find if placed at random,
    # one to each of the page's places a window apart.
    by_chance: float = 0.0
    by_chance_thrice: float = 0.0


def evaluate(*, shown: int = 3, letters: int = 40, per_page: int = 2, seed: int = 7) -> Evaluation:
    """Hide all but `shown` of a page's examples of a letter, search, and count the hidden ones found.

    A letter qualifies with at least `shown + 3` typical examples by one hand
    on one page. The other glyphs marked on the page stay marked, as in use. A
    hidden example is found when a proposal's centre falls in its box. The
    pages are annotated in part, so a proposal on an unmarked example of the
    letter counts as a miss: the result is a lower bound.
    """
    import random

    from apps.ml.providers.base import ProviderError
    from apps.ml.providers.page_search import SUPPRESS_CELLS, WINDOW_BLOCKS, find, page_grey

    rng = random.Random(seed)
    groups: dict[int, set[tuple[int | None, int]]] = {}
    for image_id, hand_id, allograph_id in (
        Graph.objects.filter(allograph_id__gte=1, annotation_type=Graph.AnnotationType.IMAGE)
        .values_list("item_image_id", "hand_id", "allograph_id")
        .distinct()
    ):
        groups.setdefault(image_id, set()).add((hand_id, allograph_id))
    pages = sorted(groups)
    rng.shuffle(pages)

    result = Evaluation(
        letters=0, pages=0, shown=shown, hidden=0, within_hidden=0, within_thrice=0, unavailable_pages=0
    )
    for image_id in pages:
        if result.letters >= letters:
            break
        try:
            page = page_letters(ItemImage.objects.get(pk=image_id))
        except images.ImageUnavailable:
            result.unavailable_pages += 1
            continue
        searched = 0
        for hand_id, allograph_id in sorted(groups[image_id], key=lambda key: (key[1], key[0] or 0)):
            if searched >= per_page or result.letters >= letters:
                break
            boxes = [box for _, box in page.examples(allograph_id, hand_id)]
            if len(boxes) < shown + 3:
                continue
            rng.shuffle(boxes)
            examples, hidden = boxes[:shown], boxes[shown:]
            side = statistics.median(max(w, h) for _, _, w, h in examples)
            scale = HOG_SIDE / side
            if max(page.width, page.height) * scale > MAX_RENDITION:
                continue
            try:
                rendered = Image.open(io.BytesIO(images.rendition(page.image, width=round(page.width * scale))))
            except images.ImageUnavailable:
                result.unavailable_pages += 1
                break
            scale = rendered.size[0] / page.width
            grey = page_grey(rendered)
            marked = [box for box in page.marked if box not in hidden]
            try:
                proposals = find(
                    grey,
                    [[v * scale for v in box] for box in examples],
                    [[v * scale for v in box] for box in marked],
                    3 * len(hidden),
                )
            except ProviderError:
                continue  # every example at the page's edge, say: nothing to search by
            remaining = list(hidden)
            for rank, proposal in enumerate(proposals, start=1):
                cx = (proposal["x"] + proposal["w"] / 2) / scale
                cy = (proposal["y"] + proposal["h"] / 2) / scale
                for box in remaining:
                    x, y, w, h = box
                    if x <= cx <= x + w and y <= cy <= y + h:
                        remaining.remove(box)
                        result.within_hidden += rank <= len(hidden)
                        result.within_thrice += 1
                        break
            places = max(
                1.0,
                (grey.shape[0] // HOG_CELL - WINDOW_BLOCKS)
                * (grey.shape[1] // HOG_CELL - WINDOW_BLOCKS)
                / (2 * SUPPRESS_CELLS + 1) ** 2,
            )
            result.by_chance += len(hidden) * min(1.0, len(hidden) / places)
            result.by_chance_thrice += len(hidden) * min(1.0, 3 * len(hidden) / places)
            result.hidden += len(hidden)
            result.letters += 1
            searched += 1
        result.pages += bool(searched)
    return result
