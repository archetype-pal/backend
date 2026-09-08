"""W1.1 — glyph region proposals.

**A different method from the one the plan describes, reaching the same
deliverable.** §7.2 specifies a box detector trained on the 20,539 existing
boxes, or a promptable segmentation model used zero-shot. This is neither: it
asks a hosted multimodal model to read the page and name the letters it sees.
That became possible when the programme moved to hosted inference, and it needs
no GPU, no training run and no labelled split — but it is also unmeasured, and
the throughput and accuracy claims in §7.2 belong to the trained detector, not
to this. Scoring it against a held-out split (W0.3) is what would let either
method be preferred on evidence.

What is *not* different is where the output goes. Proposals land in W0.5's
`GraphProposal` queue and nowhere else, so C1 holds here exactly as it does for
a trained model: no annotation enters the record without a named human
accepting it.
"""

from collections.abc import Iterable
import logging
from typing import Any

from django.db.models import Count

from apps.annotations.models import Graph, GraphProposal
from apps.annotations.services import proposals
from apps.manuscripts.models import ItemImage
from apps.ml.answers import parse_json
from apps.ml.models import MLJob
from apps.ml.services import InferenceService
from apps.scribes.models import Hand
from apps.symbols_structure.models import Allograph
from apps.vision import images

logger = logging.getLogger(__name__)

TASK = "W1.1"
PROVIDER = "openrouter"
MAX_TOKENS = 8000

SYSTEM = """You are assisting a palaeography project with the annotation of Scottish royal
charters, c. 1100-1250, written in Latin in a twelfth-century documentary hand.

You are given one page. Locate individual **letter forms** — single graphs, not
words, not lines — and report a bounding box for each.

Report only letters you can actually see and identify. This corpus is annotated
letter by letter by palaeographers, who will check every box you return; a box
around the wrong thing costs more of their time than a letter you skipped.

Coordinates are fractions of the page, origin at the TOP LEFT:
`x` and `y` are the top-left corner, `w` and `h` the width and height, all
between 0 and 1. A single letter is small — typically well under 5% of the page
in area.

Return JSON only, no prose:

{"glyphs": [{"letter": "<the letter, e.g. a, s, d>",
             "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0,
             "confidence": 0.0}]}

Return at most 40 glyphs, the ones you are most confident about. Return an empty
list rather than guessing at an illegible or damaged page."""

PROMPT = "Locate the individual letter forms on this charter page and return their bounding boxes as JSON."


def unannotated(limit_per_image: int = 1) -> list[ItemImage]:
    """Images carrying fewer than `limit_per_image` annotations.

    Ordered least-annotated first. 424 of 3,199 images carry any annotation at
    all, so the useful work is overwhelmingly on pages nobody has started —
    which is also where a proposal is worth most and where the model has no
    existing boxes to lean on.
    """
    return list(
        ItemImage.objects.annotate(annotations=Count("graphs"))
        .filter(annotations__lt=limit_per_image)
        .order_by("annotations", "id")
    )


def default_hand(image: ItemImage) -> Hand | None:
    """The hand a proposal is attributed to, by the platform's own convention.

    `Hand.Meta.ordering` already encodes it — `is_default`, then `priority`,
    then display order — so this reads the existing rule rather than inventing
    a second one. `Graph` requires a hand for an image annotation, so a page
    whose charter has no hand recorded yields proposals that cannot be accepted
    until somebody adds one. That is the correct outcome: attributing a letter
    to a scribe is a scholarly act, and guessing it here would put an
    unattributable claim in front of a reviewer wearing a hand's name.
    """
    hand: Hand | None = Hand.objects.filter(item_part_id=image.item_part_id).first()
    return hand


def parse(text: str) -> list[dict[str, Any]]:
    """Model output → boxes that could become proposals."""
    payload = parse_json(text)
    glyphs = payload.get("glyphs") if isinstance(payload, dict) else None
    if not isinstance(glyphs, list):
        raise ValueError("Expected an object with a 'glyphs' list.")

    cleaned = []
    for item in glyphs:
        if not isinstance(item, dict) or not images.plausible(item):
            continue
        letter = str(item.get("letter", "")).strip()
        if not letter:
            continue
        confidence = item.get("confidence")
        cleaned.append(
            {
                "letter": letter,
                "x": float(item["x"]),
                "y": float(item["y"]),
                "w": float(item["w"]),
                "h": float(item["h"]),
                "confidence": float(confidence) if isinstance(confidence, int | float) else None,
            }
        )
    return cleaned


def _allographs() -> dict[str, int]:
    """Letter name → allograph id, lowercased.

    97 of 103 allographs are attested in the corpus, and the model is asked for
    a letter rather than an allograph name — so an unmatched name is dropped
    rather than mapped to something near it. Inventing the palaeographic class
    is precisely the judgement the reviewer exists to make.
    """
    return {name.lower(): pk for pk, name in Allograph.objects.values_list("id", "name")}


def run(
    *,
    limit: int | None = None,
    provider: str = PROVIDER,
    model: str | None = None,
    actor: Any | None = None,
    dry_run: bool = False,
    selection: Iterable[ItemImage] | None = None,
) -> dict[str, int]:
    """Propose glyph regions for unannotated pages. Returns a per-outcome tally."""
    service = InferenceService()
    allograph_ids = _allographs()
    tally = {
        "selected": 0,
        "proposed": 0,
        "unmatched": 0,
        "refused": 0,
        "failed": 0,
        "unparsable": 0,
        "unavailable": 0,
    }

    for image in selection if selection is not None else unannotated():
        if limit is not None and tally["selected"] >= limit:
            break
        tally["selected"] += 1

        try:
            width, height = images.dimensions(image)
            if dry_run:
                continue
            payload = images.data_url(image)
        except images.ImageUnavailable as exc:
            # Not a failure of the model; the page could not be put in front of
            # one. Counted separately so a broken image server does not read as
            # a bad model.
            tally["unavailable"] += 1
            logger.warning("Skipping image %s: %s", image.pk, exc)
            continue

        inputs = {
            "system": SYSTEM,
            "prompt": PROMPT,
            "images": [payload],
            "model": model,
            "max_tokens": MAX_TOKENS,
        }
        job = service.submit(task=TASK, provider=provider, inputs=inputs, actor=actor, dispatch=False)
        if job.status == MLJob.Status.REFUSED:
            tally["refused"] += 1
            logger.warning("%s refused: %s", TASK, job.error)
            break

        job = service.run(job.pk, inputs=inputs)
        if job.status != MLJob.Status.SUCCEEDED:
            tally["failed"] += 1
            continue

        try:
            boxes = parse(str(getattr(job, "_output_text", "") or ""))
        except ValueError as exc:
            tally["unparsable"] += 1
            logger.warning("%s could not parse job %s: %s", TASK, job.pk, exc)
            continue

        hand = default_hand(image)
        for box in boxes:
            allograph_id = allograph_ids.get(box["letter"].lower())
            if allograph_id is None:
                tally["unmatched"] += 1
                continue
            proposals.propose(
                item_image_id=image.pk,
                annotation=images.ring_from_box(box, width=width, height=height),
                allograph_id=allograph_id,
                hand_id=hand.pk if hand else None,
                annotation_type=str(Graph.AnnotationType.IMAGE),
                confidence=box["confidence"],
                ml_job_id=job.pk,
            )
            tally["proposed"] += 1

    return tally


def queue_depth() -> int:
    """Pending annotation proposals — §8.6's stop rule reads this."""
    return int(GraphProposal.objects.filter(status=GraphProposal.Status.PENDING).count())
