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

**Measured: the off-the-shelf medieval-Latin model.** `--provider kraken` is
§7.2's baseline as published: CATMuS Medieval 1.5.0 reading the lines Kraken's
default segmenter finds (`htr/`), neither trained on this corpus. Over the 180
transcribed pages with a local image in November 2026 (it found no lines on
one), its median CER is 0.32 (mean 0.36, middle half 0.27-0.42, worst 0.87). No page reaches the
10% target; the best is 0.18. Drafting the tail from it is not worth a
reviewer's time.

Setting aside what is convention rather than reading (the normalised CER:
case, ⁊ against et, punctuation and the suspension mark) brings the median only
to 0.27, and 22 pages under 0.20. Scored against the edition's text instead
(`--style edited`, expansions kept), it is 0.335, normalised 0.29: CATMuS keeps
the scribe's abbreviations, so the editors' expansions count against it. Two
causes stand out on the pages read closely, and a better reader alone would fix
neither:

- the expert transcriptions expand abbreviations without marking the
  expansion, while CATMuS keeps the scribe's abbreviation, so a faithful
  reading still counts as missing letters;
- the segmenter, given the whole photograph, finds lines in seals, rulers and
  colour cards: 71 lines on one charter whose transcription has nine.

On a 12-page probe, a TrOCR model trained on medieval Latin
(LaMOP/TrOCR_Manicule_2026_Latin_Medieval), reading the lines the segmenter
found, came out level with CATMuS reading the same lines: median 0.417 against
0.428. But where it cannot read, it writes plausible Latin, which a reviewer is
less likely to catch than a visible garble. Dropping CATMuS's lines below 0.8
mean confidence brought its probe median from 0.423 to 0.357. That threshold
was tuned on those same 12 pages and is not built.

**Measured: a hosted multimodal model.** `--provider claude`, Claude Fable 5.1
reading the whole page at up to 2,576 pixels with high effort (`--size 2576
--effort high --max-tokens 32000`), over the same 180 pages in November 2026.
It beats CATMuS on every one of the 179 pages both read, in both styles.

- Asked for the edition's text (`--style edited`), its median CER is 0.062
  (mean 0.077, middle half 0.04-0.09, worst 0.47). 142 pages are under the 10%
  target and 172 under 0.20. Normalised, the median is 0.039 and 161 pages are
  under 10%. This meets §7.2's target.
- Asked for the scribe's letters (`--style diplomatic`), it is 0.21 (mean 0.22,
  middle half 0.18-0.25, best 0.11), normalised 0.18, and no page reaches 10%.
  The unmarked expansions count against it as they do against CATMuS; how
  much of the score they account for was not measured.

Of the eight edited-style pages above 0.20, the worst two have unusual
references: one transcription ends by repeating its opening address, and the
other begins in mid-sentence.

Two cautions before drafting from it:

- The editions are published, so the model may have seen these texts in
  training, and the tail has no edition it could have seen. Only a reviewer's
  check of a sample of drafted tail pages measures that.
- The ledger puts a page at about $0.28 in the edited style (the exemplars and
  the written-out expansions) and $0.17 in the diplomatic one. Drafting the
  2,713-page tail once in the edited style costs about $760.

Drafting the tail in the edited style is now worth a reviewer's time. Not
measured: Transkribus, which needs an account, and the other hosted models
reached through OpenRouter, the default provider, which need an OpenRouter
key.
"""

from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import functools
import html
from itertools import islice
import logging
import re
from typing import Any
from xml.sax.saxutils import escape

from django.db import connections

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
# What the editor wrote rather than the scribe: an abbreviation's expansion,
# and text supplied where the parchment is lost.
_EDITORIAL = re.compile(r"<(ex|supplied)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_LINE_BREAK = re.compile(r"<lb\b[^>]*?(?:/>|>[^<]*</lb\s*>)", re.IGNORECASE)
_BLOCK_TAGS = re.compile(r"</?(?:p|div|ab|head|br)\b[^>]*>", re.IGNORECASE)
_SUPPLIED = re.compile(r"<supplied\b[^>]*>.*?</supplied\s*>", re.IGNORECASE | re.DOTALL)
_NOT_EX = re.compile(r"<(?!/?ex\b)[^>]+>", re.IGNORECASE)
# An expansion a model wrote, once its line has been escaped for TEI.
_EX_ESCAPED = re.compile(r"&lt;ex&gt;([^&]*?)&lt;/ex&gt;")
# What a normalised score leaves out: punctuation, the suspension mark, and the
# private-use code points (MUFI) some editors give medieval punctuation.
_PUNCTUATION = re.compile(r"[.,;:·…’'!?\ue000-\uf8ff]")

DIPLOMATIC = "diplomatic"
EDITED = "edited"
STYLES = (DIPLOMATIC, EDITED)
# Transcriptions shown to the model as the edition's convention, and so never scored.
EXEMPLARS = 3
EXEMPLAR_LINES = 10

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

SYSTEM_EDITED = """You are transcribing a Scottish royal charter, c. 1100-1250, written in Latin in
a twelfth-century documentary hand, for this corpus's edition.

Produce the edition's text, line by line, in its conventions, which the
examples below show:

- **Expand abbreviations and suspensions**, putting the letters you supply in
  `<ex>` and `</ex>`: `Scott<ex>orum</ex>`, `Will<ex>elm</ex>o`, `gr<ex>ati</ex>a`.
- Where a suspended name or place cannot be expanded with confidence, leave it
  as written and mark the suspension with `’`: `andr’`, `Coldingham’`.
- Write the tironian et as `et`.
- **Keep the scribe's spelling** (`uilla`, `seruientibus`, `tocius`) and word
  order. Do not correct the Latin.
- Capitalise and punctuate as the examples do.
- Keep the manuscript's line breaks: one entry in `lines` per written line.
- Where you cannot read something, write `[...]` rather than guessing. An
  illegible passage marked as illegible is useful; a plausible invention is
  worse than a gap, because a reader cannot tell it from a reading.

The opening lines of three other charters, as the edition gives them:

{examples}

Return JSON only, no prose:

{"lines": ["<line 1>", "<line 2>", ...], "notes": "<condition or legibility, or empty>"}"""

PROMPT = "Transcribe this charter line by line and return the lines as JSON."


def plain_text(content: str) -> str:
    """The transcription as the parchment has it, to score a reading against.

    CER is measured on what the transcriptions say, not on how they are
    encoded: comparing markup would score the model on tags it was never asked
    for. Nor is it measured on what the editor added. The model is told to
    expand nothing and supply nothing, so an expansion (`<ex>`) or supplied
    text left in the truth counts every abbreviation it rightly left alone as
    an error. The rest of the markup goes without a space, since it sits
    inside words; a line break becomes one, as the model's lines are joined
    with one; and entities are decoded.
    """
    text = _EDITORIAL.sub("", content or "")
    text = _LINE_BREAK.sub(" ", text)
    text = _BLOCK_TAGS.sub(" ", text)
    text = html.unescape(_TAGS.sub("", text))
    return re.sub(r"\s+", " ", text).strip()


def edition_text(content: str) -> str:
    """The transcription as the editor reads it, to score an edited reading against.

    `plain_text` with the expansions kept, since an edited reading is asked to
    expand, and without text supplied where the parchment is lost, which no
    reading of the page can recover.
    """
    text = _SUPPLIED.sub("", content or "")
    text = _LINE_BREAK.sub(" ", text)
    text = _BLOCK_TAGS.sub(" ", text)
    text = html.unescape(_TAGS.sub("", text))
    return re.sub(r"\s+", " ", text).strip()


def edition_lines(content: str) -> list[str]:
    """The transcription's written lines as the edition gives them, its `<ex>` kept: an example for a model."""
    text = _SUPPLIED.sub("", content or "")
    text = _BLOCK_TAGS.sub(" ", text)
    lines = []
    for segment in _LINE_BREAK.split(text):
        line = re.sub(r"\s+", " ", html.unescape(_NOT_EX.sub("", segment))).strip()
        if line:
            lines.append(line)
    return lines


def normalised(text: str) -> str:
    """A reading without what editors do differently: case, the tironian et, punctuation.

    The corpus's editors did not share one convention (most write `et`, some
    keep `⁊`; some capitalise every word of an address), so a raw CER counts
    a convention a model was not shown as misreading. Scoring this as well
    separates the two. It is not the §7.2 target, which is the raw CER.
    """
    text = text.casefold().replace("⁊", "et")
    return re.sub(r"\s+", " ", _PUNCTUATION.sub(" ", text)).strip()


def exemplars() -> list[ImageText]:
    """The transcriptions an edited reading is shown, chosen by rule so every run shows the same.

    The first, by id, that follow most of the corpus: they mark expansions
    with `<ex>` (379 of 403 do), mark suspensions with `’` (297) and write
    `et` rather than `⁊` (all but 80), and run to at least ten lines.
    """
    chosen = []
    for text in transcribed():
        reading = plain_text(text.content)
        if (
            "<ex" in text.content.lower()
            and "’" in reading
            and "⁊" not in reading
            and len(edition_lines(text.content)) >= EXEMPLAR_LINES
        ):
            chosen.append(text)
        if len(chosen) == EXEMPLARS:
            break
    return chosen


def system_for(style: str, shown: Iterable[ImageText] = ()) -> str:
    """The instructions for a style: a diplomatic reading, or the edition's, with its examples."""
    if style == DIPLOMATIC:
        return SYSTEM
    if style != EDITED:
        raise ValueError(f"No HTR style {style!r}; choose one of {', '.join(STYLES)}.")
    examples = "\n\n".join(
        "<example>\n" + "\n".join(edition_lines(text.content)[:EXEMPLAR_LINES]) + "\n</example>" for text in shown
    )
    return SYSTEM_EDITED.replace("{examples}", examples)


def reading_text(lines: list[str]) -> str:
    """A model's lines as one text to score, any markup it wrote (its `<ex>`) left out but not its content."""
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", " ".join(lines)))).strip()


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
    export rather than living only in our database. An expansion an edited
    reading marks becomes the corpus's `<ex>`; any other markup is escaped.
    """
    body = f'<div type="transcription" resp="#machine-draft" source="{escape(model)}">'
    for line in payload["lines"]:
        # An expansion the model marked stays one, as the corpus marks its own.
        body += f'<lb source="ms"/>{_EX_ESCAPED.sub(r"<ex>\1</ex>", escape(line))}'
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
    size: int = images.RENDITION,
    effort: str | None = None,
    max_tokens: int = MAX_TOKENS,
    system: str = SYSTEM,
) -> tuple[MLJob | None, dict[str, Any] | None, str]:
    """One page through the model. Returns (job, parsed, outcome).

    `size` bounds the page's longer side in pixels; the image server never
    enlarges it. `effort` is passed to a provider that takes one.
    """
    try:
        payload_url = images.data_url(image, size=size)
    except images.ImageUnavailable as exc:
        logger.warning("Skipping image %s: %s", image.pk, exc)
        return None, None, "unavailable"

    inputs: dict[str, Any] = {
        "system": system,
        "prompt": PROMPT,
        "images": [payload_url],
        "model": model,
        "max_tokens": max_tokens,
    }
    if effort:
        inputs["effort"] = effort
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


Reading = tuple[MLJob | None, dict[str, Any] | None, str]


def _in_thread(ask: Callable[[ItemImage], Reading], image: ItemImage) -> Reading:
    """`ask` on a worker thread, which closes its own database connection when done."""
    try:
        return ask(image)
    finally:
        connections.close_all()


def _read[T](
    pages: list[T], image_of: Callable[[T], ItemImage], ask: Callable[[ItemImage], Reading], *, workers: int
) -> Iterator[tuple[int, T, Reading]]:
    """Each page's reading with its position in `pages`, `workers` pages at a time.

    With one worker, in order on this thread. With more, as each finishes, so
    one slow page holds up no other: a page is started when another finishes.
    A refusal stops the run either way. It means the switch is off or a cap
    is reached, so every page not yet started would be refused too, and none
    is. Pages already being read finish and are reported.
    """
    if workers <= 1:
        for position, page in enumerate(pages):
            reading = ask(image_of(page))
            yield position, page, reading
            if reading[2] == "refused":
                return
        return

    waiting = iter(enumerate(pages))
    with ThreadPoolExecutor(max_workers=workers) as pool:

        def start(count: int) -> dict[Future[Reading], int]:
            return {pool.submit(_in_thread, ask, image_of(page)): position for position, page in islice(waiting, count)}

        running = start(workers)
        refused = False
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                position = running.pop(future)
                reading = future.result()
                yield position, pages[position], reading
                refused = refused or reading[2] == "refused"
                if not refused:
                    running |= start(1)


def transcribe(
    *,
    limit: int | None = None,
    provider: str = PROVIDER,
    model: str | None = None,
    actor: Any | None = None,
    dry_run: bool = False,
    selection: Iterable[ItemImage] | None = None,
    size: int = images.RENDITION,
    effort: str | None = None,
    max_tokens: int = MAX_TOKENS,
    workers: int = 1,
    style: str = DIPLOMATIC,
) -> dict[str, int]:
    """Draft transcriptions for images that have none, `workers` pages at a time.

    Drafts, never Live: the same gate `import-htr` uses, and what keeps C1 true
    for text. A draft is a proposal wearing the editorial workflow's clothes.
    """
    service = InferenceService()
    tally = {"selected": 0, "drafted": 0, "refused": 0, "failed": 0, "unparsable": 0, "unavailable": 0}
    system = system_for(style, exemplars() if style == EDITED else ())
    pages = list(islice(selection if selection is not None else untranscribed(), limit))
    tally["selected"] = len(pages)
    if dry_run:
        return tally

    ask = functools.partial(
        _ask,
        service,
        provider=provider,
        model=model,
        actor=actor,
        size=size,
        effort=effort,
        max_tokens=max_tokens,
        system=system,
    )
    for _position, image, (job, payload, outcome) in _read(pages, lambda image: image, ask, workers=workers):
        if outcome == "refused":
            tally["refused"] += 1
            continue
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
    size: int = images.RENDITION,
    effort: str | None = None,
    max_tokens: int = MAX_TOKENS,
    workers: int = 1,
    style: str = DIPLOMATIC,
) -> dict[str, Any]:
    """Score the same prompt against expert transcriptions, `workers` pages at a time. Writes nothing.

    Reports median CER as well as mean: one unreadable page produces a CER above
    1.0 and drags a mean anywhere, and a headline number that a single failure
    can move is not a baseline. The per-image scores keep the selection's
    order, however the pages finish.

    `style` is what the model is asked for and scored against: a diplomatic
    reading against `plain_text`, or the edition's against `edition_text`. The
    transcriptions an edited reading is shown as examples are left out of the
    selection, so none is scored on a text it was given.
    """
    service = InferenceService()
    rates: list[float] = []
    normalised_rates: list[float] = []
    scored: dict[int, dict[str, Any]] = {}
    tally = {"selected": 0, "scored": 0, "refused": 0, "failed": 0, "unparsable": 0, "unavailable": 0}
    shown = exemplars() if style == EDITED else []
    system = system_for(style, shown)
    held_out = {text.pk for text in shown}
    pages = [
        text for text in islice(selection if selection is not None else transcribed(), limit) if text.pk not in held_out
    ]
    tally["selected"] = len(pages)
    truth_of = edition_text if style == EDITED else plain_text

    ask = functools.partial(
        _ask,
        service,
        provider=provider,
        model=model,
        actor=actor,
        size=size,
        effort=effort,
        max_tokens=max_tokens,
        system=system,
    )
    for position, text, (_job, payload, outcome) in _read(pages, lambda text: text.item_image, ask, workers=workers):
        if outcome != "ok" or payload is None:
            tally[outcome if outcome in tally else "failed"] += 1
            continue

        truth = truth_of(text.content)
        predicted = reading_text(payload["lines"])
        rate = character_error_rate(truth, predicted)
        normalised_rate = character_error_rate(normalised(truth), normalised(predicted))
        rates.append(rate)
        normalised_rates.append(normalised_rate)
        scored[position] = {
            "image_text_id": text.pk,
            "item_image_id": text.item_image_id,
            "cer": round(rate, 4),
            "cer_normalised": round(normalised_rate, 4),
        }
        tally["scored"] += 1
    per_image = [scored[position] for position in sorted(scored)]

    ordered = sorted(rates)
    summary: dict[str, Any] = dict(tally)
    summary["mean_cer"] = round(sum(rates) / len(rates), 4) if rates else None
    summary["median_cer"] = round(ordered[len(ordered) // 2], 4) if ordered else None
    summary["worst_cer"] = round(ordered[-1], 4) if ordered else None
    summary["target_met"] = bool(summary["median_cer"] is not None and summary["median_cer"] < 0.10)
    ordered_normalised = sorted(normalised_rates)
    summary["median_cer_normalised"] = round(ordered_normalised[len(ordered_normalised) // 2], 4) if rates else None
    summary["mean_cer_normalised"] = round(sum(normalised_rates) / len(normalised_rates), 4) if rates else None
    summary["style"] = style
    summary["exemplars"] = sorted(held_out)
    summary["per_image"] = per_image
    return summary
