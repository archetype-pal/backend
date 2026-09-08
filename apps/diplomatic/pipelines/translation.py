"""W2.4 — English translation drafts for the untranslated tail.

Three requirements the roadmap attaches to this item, all of them here:

**The tail is 72 images**, measured: a transcription with no translation. Not
the whole corpus — most charters already have a published translation, and
re-translating those would be work nobody asked for.

**A draft and a published human translation must be able to coexist.** The
schema allows one translation per image, so an accepted draft is created only
where none exists; where one appears in the meantime, acceptance refuses rather
than overwriting a scholar's work.

**Machine-drafted lineage must be durable and public.** §8.3 is explicit that a
ledger entry is not enough: an approved draft that looks identical to a human
translation in the public render is the exact harm the principles exist to
prevent. So the draft carries a TEI `@resp` attribute naming the model, which
travels into every export, and approval never clears it.
"""

from apps.diplomatic.models import Proposal
from apps.diplomatic.pipelines.base import Pipeline, Unit, register
from apps.diplomatic.pipelines.extraction import plain_text
from apps.manuscripts.models import ImageText
from apps.ml.answers import parse_json

SYSTEM = """You are drafting an English translation of a Scottish royal charter,
c. 1100-1250, from its Latin transcription, for expert review.

This is a draft, not an edition. A palaeographer will revise it. Where the Latin
is ambiguous or damaged, say so in a bracketed note rather than choosing a
reading silently — the note is more useful than a smooth sentence that hides a
decision.

Conventions:
- Keep personal and place names in the form the charter uses; do not modernise
  or identify them.
- Preserve the diplomatic structure: address, salutation, notification,
  disposition, witnesses, dating.
- Render formulaic clauses as formulae, not as literal word-for-word English.

Return JSON only, no prose:

{"translation": "<the draft>", "notes": "<uncertainties, or empty>"}"""


def untranslated() -> list[Unit]:
    """Images with a transcription and no translation — the measured tail."""
    translated = set(ImageText.objects.filter(type="Translation").values_list("item_image_id", flat=True))
    rows = ImageText.objects.filter(type="Transcription").values_list("id", "content", "item_image_id")
    return [
        Unit(source_type="imagetext", source_id=pk, context={"text": plain_text(content), "image_id": image_id})
        for pk, content, image_id in rows
        if image_id not in translated and (content or "").strip()
    ]


def _prompt(unit: Unit) -> tuple[str, str]:
    return SYSTEM, f"Latin transcription:\n\n{unit.context['text']}"


def parse_translation(text: str):
    payload = parse_json(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected an object with a 'translation'.")
    draft = str(payload.get("translation", "")).strip()
    if not draft:
        raise ValueError("The model returned no translation.")
    return {"translation": draft, "notes": str(payload.get("notes", "")).strip()}


def materialise_translation(proposal: Proposal, *, reviewer) -> list[ImageText]:
    """Create the translation as a DRAFT, marked as machine-drafted.

    Draft, not Live: this is the same gate `import-htr` uses, and it is what
    keeps C1 true for text as W0.5 keeps it true for annotations.
    """
    source = ImageText.objects.get(pk=proposal.source_id)
    if ImageText.objects.filter(item_image_id=source.item_image_id, type="Translation").exists():
        from apps.diplomatic.services import PipelineError

        raise PipelineError(f"Image {source.item_image_id} already has a translation; a draft must not overwrite it.")

    model = proposal.ml_job.model_name if proposal.ml_job else "unknown model"
    payload = proposal.payload
    notes = payload.get("notes", "")
    # `@resp` is TEI's own responsibility attribute, so the lineage travels into
    # every export rather than living only in our database.
    body = f'<div type="translation" resp="#machine-draft" source="{model}">'
    body += f"<p>{payload['translation']}</p>"
    if notes:
        body += f'<note type="uncertainty">{notes}</note>'
    body += "</div>"

    return [
        ImageText.objects.create(
            item_image_id=source.item_image_id,
            type="Translation",
            content=body,
            status="Draft",
        )
    ]


register(
    Pipeline(
        key="W2.4",
        description="Draft English translations for charters that have none.",
        select=untranslated,
        prompt=_prompt,
        parse=parse_translation,
        materialise=materialise_translation,
        max_tokens=8000,
    )
)
