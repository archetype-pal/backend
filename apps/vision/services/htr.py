"""W1.4 — HTR baseline over the untranscribed tail.

§7.2 sets the target as *< 10% CER measured against an off-the-shelf
medieval-Latin model*, and §10.4's replanning trigger says that if such a
baseline is already good enough we integrate rather than train. A hosted
multimodal model is a third option that did not exist when that was written and
sits squarely in the same spirit: nothing is trained, and the question is
entirely empirical.

So this ships with its measurement rather than after it. `transcribe()` drafts
the untranscribed tail; `evaluate()` runs the same prompt over pages that
*already* have an expert transcription and reports CER against it. The second
is the one that decides whether the first is worth running: on this corpus,
2,713 images have no transcription and 485 do, and the 485 are the only
evidence about the 2,713 anyone has.

**Not a comparison against CATMuS-Medieval or Transkribus.** Those baselines
are still owed. This measures one hosted model against expert transcriptions;
it does not tell you it is the best available option.
"""

from collections.abc import Iterable
import logging
import re
from typing import Any
from xml.sax.saxutils import escape

from apps.manuscripts.models import ImageText, ItemImage
from apps.ml.answers import parse_json
from apps.ml.evaluation import character_error_rate
from apps.ml.models import MLJob
from apps.ml.services import InferenceService
from apps.vision import images

logger = logging.getLogger(__name__)

TASK = "W1.4"
PROVIDER = "openrouter"
MAX_TOKENS = 8000

_TAGS = re.compile(r"<[^>]+>")

SYSTEM = """You are transcribing a Scottish royal charter, c. 1100-1250, written in Latin in
a twelfth-century documentary hand.

Produce a diplomatic transcription: what is on the parchment, line by line, not
a normalised or edited text.

- **Expand nothing.** Leave abbreviations and suspensions as written. Do not
  silently supply what the scribe contracted.
- **Do not normalise spelling, word division or capitalisation.**
- Keep the manuscript's line breaks: one entry in `lines` per written line.
- Where you cannot read something, write `[...]` rather than guessing. An
  illegible passage marked as illegible is useful; a plausible invention is
  worse than a gap, because a reader cannot tell it from a reading.

Return JSON only, no prose:

{"lines": ["<line 1>", "<line 2>", ...], "notes": "<condition or legibility, or empty>"}"""

PROMPT = "Transcribe this charter line by line and return the lines as JSON."


def plain_text(content: str) -> str:
    """TEI stripped to comparable text.

    CER is measured on what the transcriptions say, not on how they are encoded.
    Comparing markup would score the model on tags it was never asked for.
    """
    return re.sub(r"\s+", " ", _TAGS.sub(" ", content or "")).strip()


def untranscribed() -> list[ItemImage]:
    """The 2,713 images with no transcription — the tail this item exists for."""
    transcribed = set(
        ImageText.objects.filter(type=ImageText.Type.TRANSCRIPTION).values_list("item_image_id", flat=True)
    )
    return [image for image in ItemImage.objects.order_by("id") if image.pk not in transcribed]


def transcribed() -> list[ImageText]:
    """Published transcriptions — the only ground truth this corpus has."""
    return list(
        ImageText.objects.filter(
            type=ImageText.Type.TRANSCRIPTION,
            status__in=[ImageText.Status.LIVE, ImageText.Status.REVIEWED],
        )
        .exclude(content="")
        .select_related("item_image")
        .order_by("id")
    )


def parse(text: str) -> dict[str, Any]:
    payload = parse_json(text)
    lines = payload.get("lines") if isinstance(payload, dict) else None
    if not isinstance(lines, list):
        raise ValueError("Expected an object with a 'lines' list.")
    cleaned = [str(line).strip() for line in lines if str(line).strip()]
    if not cleaned:
        raise ValueError("The model returned no lines.")
    return {"lines": cleaned, "notes": str(payload.get("notes", "")).strip()}


def to_tei(payload: dict[str, Any], *, model: str) -> str:
    """Lines → TEI, with the line breaks the corpus already uses.

    `<lb source="ms">` is the corpus's own convention — 474 of 485 existing
    transcriptions carry it, 5,071 tags in all — so a machine draft is encoded
    the same way a human one is and needs no special handling downstream.
    `@resp` is what marks it as machine-drafted, and it travels into every
    export rather than living only in our database.
    """
    body = f'<div type="transcription" resp="#machine-draft" source="{escape(model)}">'
    for line in payload["lines"]:
        body += f'<lb source="ms"/>{escape(line)}'
    if payload.get("notes"):
        body += f'<note type="condition">{escape(payload["notes"])}</note>'
    return body + "</div>"


def _ask(
    service: InferenceService,
    image: ItemImage,
    *,
    provider: str,
    model: str | None,
    actor: Any | None,
) -> tuple[MLJob | None, dict[str, Any] | None, str]:
    """One page through the model. Returns (job, parsed, outcome)."""
    try:
        payload_url = images.data_url(image)
    except images.ImageUnavailable as exc:
        logger.warning("Skipping image %s: %s", image.pk, exc)
        return None, None, "unavailable"

    inputs = {
        "system": SYSTEM,
        "prompt": PROMPT,
        "images": [payload_url],
        "model": model,
        "max_tokens": MAX_TOKENS,
    }
    job = service.submit(task=TASK, provider=provider, inputs=inputs, actor=actor, dispatch=False)
    if job.status == MLJob.Status.REFUSED:
        logger.warning("%s refused: %s", TASK, job.error)
        return job, None, "refused"

    job = service.run(job.pk, inputs=inputs)
    if job.status != MLJob.Status.SUCCEEDED:
        return job, None, "failed"

    try:
        return job, parse(str(getattr(job, "_output_text", "") or "")), "ok"
    except ValueError as exc:
        logger.warning("%s could not parse job %s: %s", TASK, job.pk, exc)
        return job, None, "unparsable"


def transcribe(
    *,
    limit: int | None = None,
    provider: str = PROVIDER,
    model: str | None = None,
    actor: Any | None = None,
    dry_run: bool = False,
    selection: Iterable[ItemImage] | None = None,
) -> dict[str, int]:
    """Draft transcriptions for images that have none.

    Drafts, never Live: the same gate `import-htr` uses, and what keeps C1 true
    for text. A draft is a proposal wearing the editorial workflow's clothes.
    """
    service = InferenceService()
    tally = {"selected": 0, "drafted": 0, "refused": 0, "failed": 0, "unparsable": 0, "unavailable": 0}

    for image in selection if selection is not None else untranscribed():
        if limit is not None and tally["selected"] >= limit:
            break
        tally["selected"] += 1
        if dry_run:
            continue

        job, payload, outcome = _ask(service, image, provider=provider, model=model, actor=actor)
        if outcome == "refused":
            tally["refused"] += 1
            break
        if outcome != "ok" or payload is None or job is None:
            tally[outcome if outcome in tally else "failed"] += 1
            continue

        if ImageText.objects.filter(item_image_id=image.pk, type=ImageText.Type.TRANSCRIPTION).exists():
            # Somebody transcribed it while this pass was running. Their work
            # wins; a machine draft must never displace it.
            logger.info("Image %s acquired a transcription mid-run; not drafting.", image.pk)
            continue

        ImageText.objects.create(
            item_image_id=image.pk,
            type=ImageText.Type.TRANSCRIPTION,
            content=to_tei(payload, model=job.model_name or "unknown model"),
            status=ImageText.Status.DRAFT,
        )
        tally["drafted"] += 1

    return tally


def evaluate(
    *,
    limit: int | None = None,
    provider: str = PROVIDER,
    model: str | None = None,
    actor: Any | None = None,
    selection: Iterable[ImageText] | None = None,
) -> dict[str, Any]:
    """Score the same prompt against expert transcriptions. Writes nothing.

    Reports median CER as well as mean: one unreadable page produces a CER above
    1.0 and drags a mean anywhere, and a headline number that a single failure
    can move is not a baseline.
    """
    service = InferenceService()
    rates: list[float] = []
    per_image: list[dict[str, Any]] = []
    tally = {"selected": 0, "scored": 0, "refused": 0, "failed": 0, "unparsable": 0, "unavailable": 0}

    for text in selection if selection is not None else transcribed():
        if limit is not None and tally["selected"] >= limit:
            break
        tally["selected"] += 1

        job, payload, outcome = _ask(service, text.item_image, provider=provider, model=model, actor=actor)
        if outcome == "refused":
            tally["refused"] += 1
            break
        if outcome != "ok" or payload is None:
            tally[outcome if outcome in tally else "failed"] += 1
            continue

        truth = plain_text(text.content)
        predicted = re.sub(r"\s+", " ", " ".join(payload["lines"])).strip()
        rate = character_error_rate(truth, predicted)
        rates.append(rate)
        per_image.append({"image_text_id": text.pk, "item_image_id": text.item_image_id, "cer": round(rate, 4)})
        tally["scored"] += 1

    ordered = sorted(rates)
    summary: dict[str, Any] = dict(tally)
    summary["mean_cer"] = round(sum(rates) / len(rates), 4) if rates else None
    summary["median_cer"] = round(ordered[len(ordered) // 2], 4) if ordered else None
    summary["worst_cer"] = round(ordered[-1], 4) if ordered else None
    summary["target_met"] = bool(summary["median_cer"] is not None and summary["median_cer"] < 0.10)
    summary["per_image"] = per_image
    return summary
