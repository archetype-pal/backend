"""W1.1 — proposing a page's letters with models trained on this corpus.

The method the plan asks for: a model trained on the corpus's expert boxes
proposes glyph regions on pages, and a reviewer accepts or rejects each. It is
built from parts that each do one thing well. Kraken with CATMuS reads the page
and places every character on its line: it reads a character inside 97% of
expert boxes, but it marks a point, not a box. The letter models (see
`htr/letters.py`, trained by `htr/train_letters.py`) draw the box an expert
would draw round each point and name the allograph. All of it runs on our own
server: no page leaves it, and nothing is billed.

**Measured by `train_letters.py`** on release `letters-2026-11-06`, on the 306
of its 424 pages with a local image, split by charter: trained on 217 pages,
watched on 24, and scored on the 1,797 expert boxes of the 65 held out. The box
model (25 epochs) drew a box at IoU ≥ 0.5 with 80.8% of them and at ≥ 0.7 with
56.6%, median IoU 0.73. Giving each character the median size of its expert
boxes did 56.2%; a hosted model (Fable 5.1) asked for coordinates put 2 of 30
boxes on a letter (see `detection`). One held-out page, image 5069, has all 125
of its boxes off its picture, so none can be found; without it the box model
did 86.8%, as the probe that chose the method predicted (85.5%, split by page).
On the boxes found, the classifier (30 epochs) named the expert's allograph for
87.1%, against 69.2% for the allograph experts most often give the character
read; at probability 0.7 or more it covered 86% of boxes and was right for 94%.
A trained model's own numbers are in its manifest (`letters.json`).

**`MIN_FIT`** was checked on the watched charters, not the held-out ones: a box
expected to fit at 0.6 or more lands on the expert's (IoU ≥ 0.5) 93.8% of the
time and keeps 85% of boxes; at 0.7, 97.0% and 67%. It stays at 0.6. A page
files the likeliest few of each allograph first, so a higher bar would mostly
cost the rare allographs, which have few candidates to choose from.

**Which letters are proposed.** A page has 1,500 to 3,000 characters; experts
mark a few examples of each allograph, not every letter. So a page gets at most
`per_allograph` proposals of each allograph, the likeliest first, and none
whose box is not expected to fit (`min_fit`) or whose allograph is in doubt
(`min_probability`). A reviewer can only accept or reject a proposal, so a
doubtful label is not worth filing. Nothing already marked or proposed on the
page is proposed again. A proposal's confidence is the box's expected fit times
the allograph's probability; the queue lists the likeliest first.

Proposals land in W0.5's `GraphProposal` queue and nowhere else.
"""

import base64
from collections.abc import Iterable
from dataclasses import dataclass
import io
import json
import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from PIL import Image

from apps.annotations.models import Graph
from apps.annotations.services import proposals
from apps.manuscripts.models import ItemImage
from apps.ml.models import MLJob
from apps.ml.services import InferenceService
from apps.symbols_structure.models import Allograph
from apps.vision import images

from . import detection, page_search

logger = logging.getLogger(__name__)

TASK = "W1.1"
PROVIDER = "letters"
# The page is sent with its longer side at most this many pixels: the most the
# service takes, and the size the letter models were trained at.
SEND_SIDE = 4000
PER_ALLOGRAPH = 3
MIN_FIT = 0.6
MIN_PROBABILITY = 0.7
MAX_PER_PAGE = 200
# Two proposals overlapping more than this are one letter proposed twice.
SAME_LETTER = 0.5

Box = tuple[float, float, float, float]  # x, y, w, h in the page's pixels, origin at the top left


@dataclass(frozen=True)
class Letter:
    """A letter the models found, in the page's full-size pixels."""

    box: Box
    allograph_id: int
    fit: float
    probability: float

    @property
    def confidence(self) -> float:
        return self.fit * self.probability


def overlap(a: Box, b: Box) -> float:
    """Intersection over union."""
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _inside(box: Box, marked: Box) -> bool:
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    return marked[0] <= cx <= marked[0] + marked[2] and marked[1] <= cy <= marked[1] + marked[3]


def choose(
    found: Iterable[Letter],
    *,
    marked: Iterable[Box] = (),
    per_allograph: int = PER_ALLOGRAPH,
    min_fit: float = MIN_FIT,
    min_probability: float = MIN_PROBABILITY,
    limit: int = MAX_PER_PAGE,
) -> list[Letter]:
    """The letters worth a reviewer's time, likeliest first."""
    marked = list(marked)
    candidates = sorted(
        (
            letter
            for letter in found
            if letter.fit >= min_fit
            and letter.probability >= min_probability
            and not any(_inside(letter.box, box) for box in marked)
        ),
        key=lambda letter: letter.confidence,
        reverse=True,
    )
    chosen: list[Letter] = []
    per: dict[int, int] = {}
    for letter in candidates:
        if len(chosen) >= limit:
            break
        if per.get(letter.allograph_id, 0) >= per_allograph:
            continue
        if any(overlap(letter.box, other.box) > SAME_LETTER for other in chosen):
            continue
        chosen.append(letter)
        per[letter.allograph_id] = per.get(letter.allograph_id, 0) + 1
    return chosen


def allograph_ids() -> dict[tuple[str, str], int]:
    """(character name, allograph name) → id: the pair the models name, matched exactly."""
    return {
        (character, name): pk for pk, character, name in Allograph.objects.values_list("id", "character__name", "name")
    }


def found_letters(output: dict[str, Any], *, width: int, ids: dict[tuple[str, str], int]) -> tuple[list[Letter], int]:
    """The service's letters in the page's full-size pixels, and how many named an allograph we do not have."""
    scale = width / output["width"]
    found, unknown = [], 0
    for letter in output["letters"]:
        allograph_id = ids.get((letter["character"], letter["allograph"]))
        if allograph_id is None:
            unknown += 1
            continue
        x, y, w, h = (float(v) * scale for v in letter["box"])
        found.append(
            Letter(box=(x, y, w, h), allograph_id=allograph_id, fit=letter["fit"], probability=letter["probability"])
        )
    return found, unknown


def propose_page(
    image: ItemImage,
    *,
    actor: Any | None = None,
    service: InferenceService | None = None,
    ids: dict[tuple[str, str], int] | None = None,
    per_allograph: int = PER_ALLOGRAPH,
) -> dict[str, int]:
    """Find one page's letters and file the likeliest as proposals. Returns a per-outcome tally."""
    tally = {"proposed": 0, "found": 0, "unknown_allograph": 0, "refused": 0, "failed": 0, "unavailable": 0}
    service = service or InferenceService()
    try:
        letters_on_page = page_search.page_letters(image)
        inputs = {"images": [images.data_url(image, size=SEND_SIDE)]}
    except images.ImageUnavailable as exc:
        tally["unavailable"] += 1
        logger.warning("Skipping image %s: %s", image.pk, exc)
        return tally

    job = service.submit(task=TASK, provider=PROVIDER, inputs=inputs, actor=actor, dispatch=False)
    if job.status == MLJob.Status.REFUSED:
        tally["refused"] += 1
        logger.warning("%s refused: %s", TASK, job.error)
        return tally
    job = service.run(job.pk, inputs=inputs)
    if job.status != MLJob.Status.SUCCEEDED:
        tally["failed"] += 1
        return tally

    found, unknown = found_letters(job._output, width=letters_on_page.width, ids=ids or allograph_ids())
    tally["found"], tally["unknown_allograph"] = len(found), unknown
    hand = detection.default_hand(image)
    for letter in choose(found, marked=letters_on_page.marked, per_allograph=per_allograph):
        x, y, w, h = letter.box
        proposals.propose(
            item_image_id=image.pk,
            annotation=images.ring_from_box(
                {
                    "x": x / letters_on_page.width,
                    "y": y / letters_on_page.height,
                    "w": w / letters_on_page.width,
                    "h": h / letters_on_page.height,
                },
                width=letters_on_page.width,
                height=letters_on_page.height,
            ),
            allograph_id=letter.allograph_id,
            hand_id=hand.pk if hand else None,
            annotation_type=str(Graph.AnnotationType.IMAGE),
            confidence=round(letter.confidence, 4),
            ml_job_id=job.pk,
        )
        tally["proposed"] += 1
    return tally


def run(
    *,
    limit: int | None = None,
    actor: Any | None = None,
    selection: Iterable[ItemImage] | None = None,
    per_allograph: int = PER_ALLOGRAPH,
) -> dict[str, int]:
    """Propose letters page by page, unannotated pages first unless `selection` names them."""
    service = InferenceService()
    ids = allograph_ids()
    tally = dict.fromkeys(
        ("selected", "proposed", "found", "unknown_allograph", "refused", "failed", "unavailable", "queue_full"), 0
    )
    for image in selection if selection is not None else detection.unannotated():
        if limit is not None and tally["selected"] >= limit:
            break
        if detection.queue_depth() >= settings.ML_REVIEW_LIMIT_LETTERS:
            tally["queue_full"] = 1
            break
        tally["selected"] += 1
        page = propose_page(image, actor=actor, service=service, ids=ids, per_allograph=per_allograph)
        for key, value in page.items():
            tally[key] += value
        if page["refused"]:
            break
    return tally


def export_pages(release: Path, out: Path) -> dict[str, int]:
    """The release's pages as the letter models are trained on them, with `pages.json` saying which is which.

    Each page is fetched as the service is sent it, its longer side at most
    SEND_SIDE. These are the holding repositories' photographs, which no
    release may redistribute: the directory is for training on this server and
    goes nowhere else. A page already exported is kept.
    """
    out.mkdir(parents=True, exist_ok=True)
    wanted: dict[int, int] = {}
    with (release / "glyphs.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("iiif_region"):
                wanted[row["item_image_id"]] = row["item_part_id"]

    index_path = out / "pages.json"
    index = {page["item_image_id"]: page for page in json.loads(index_path.read_text())} if index_path.exists() else {}
    tally = {"pages": len(wanted), "exported": 0, "kept": 0, "unavailable": 0}
    for image in ItemImage.objects.filter(pk__in=wanted).order_by("pk"):
        name = f"{image.pk}.jpg"
        if image.pk in index and (out / name).is_file():
            tally["kept"] += 1
            continue
        try:
            width, height = images.dimensions(image)
            data = base64.b64decode(images.data_url(image, size=SEND_SIDE).partition("base64,")[2])
        except images.ImageUnavailable as exc:
            tally["unavailable"] += 1
            logger.warning("Skipping image %s: %s", image.pk, exc)
            continue
        sent_width = Image.open(io.BytesIO(data)).width
        (out / name).write_bytes(data)
        index[image.pk] = {
            "item_image_id": image.pk,
            "item_part_id": wanted[image.pk],
            "file": name,
            "width": width,
            "height": height,
            "scale": sent_width / width,
        }
        tally["exported"] += 1
        index_path.write_text(json.dumps(sorted(index.values(), key=lambda p: p["item_image_id"]), indent=1))
    return tally
