"""W3.2 — curation agents. They file into the review queue; they fix nothing.

The roadmap lists four classes: missing attributions, suspicious dates,
duplicate records, untagged formulas. Two of those are already answerable
without a model — the dating audit finds inconsistent dates arithmetically, and
duplicate detection is a comparison — so the model is pointed at the one that
genuinely needs reading: whether a charter's own text contradicts the date the
catalogue gives it.

That is exactly the case `ROADMAP.md` records under Track H and that no numeric
check can see: part 228 is dated "Early 1200s" while its witness list names men
dead by 1178. The dating audit cannot find it. This can.
"""

from apps.diplomatic.models import Proposal
from apps.diplomatic.pipelines.base import Pipeline, Unit, register
from apps.diplomatic.pipelines.extraction import plain_text
from apps.manuscripts.models import ImageText
from apps.ml.answers import parse_json

SYSTEM = """You are auditing the dating of Scottish royal charters, c. 1100-1250, for a
palaeography project.

You are given a charter's Latin text and the date the catalogue currently
assigns it. Decide whether the text is consistent with that date.

The evidence that matters is internal: the witness list (when were these men
alive, and in these offices?), the titles used, references to other rulers, and
any explicit dating clause. A charter naming a chancellor who died in 1178
cannot be from the 1200s.

Do not re-date the charter. Report a disagreement and the evidence for it; a
diplomatist decides. Say "consistent" when the text neither confirms nor
contradicts the date — most charters will not settle their own dating, and a
flood of weak flags is worse than none.

Return JSON only, no prose:

{"verdict": "consistent" | "inconsistent" | "uncertain",
 "evidence": "<the wording that bears on it, quoted>",
 "reasoning": "<why, briefly>",
 "suggested_range": "<e.g. 1165x1177, or empty>"}"""


def dated_charters() -> list[Unit]:
    """Transcriptions whose charter carries a date to check against."""
    rows = ImageText.objects.filter(
        type="Transcription", item_image__item_part__historical_item__date__isnull=False
    ).values_list(
        "id",
        "content",
        "item_image__item_part__historical_item__date__date",
        "item_image__item_part__historical_item_id",
    )
    return [
        Unit(
            source_type="imagetext",
            source_id=pk,
            context={"text": plain_text(content), "date": label or "", "historical_item_id": item_id},
        )
        for pk, content, label, item_id in rows
        if (content or "").strip()
    ]


def _prompt(unit: Unit) -> tuple[str, str]:
    return SYSTEM, (f"Catalogue date: {unit.context['date']}\n\nCharter text:\n\n{unit.context['text']}")


def parse_verdict(text: str):
    payload = parse_json(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected an object with a 'verdict'.")
    verdict = str(payload.get("verdict", "")).strip().lower()
    if verdict not in {"consistent", "inconsistent", "uncertain"}:
        raise ValueError(f"Unusable verdict {verdict!r}.")
    return {
        "verdict": verdict,
        "evidence": str(payload.get("evidence", "")).strip(),
        "reasoning": str(payload.get("reasoning", "")).strip(),
        "suggested_range": str(payload.get("suggested_range", "")).strip(),
    }


def materialise_verdict(proposal: Proposal, *, reviewer) -> list:
    """Accepting a dating flag records the judgement; it changes no date.

    Deliberately creates nothing. A curation agent's output is a question put to
    a diplomatist, and the answer — re-dating a charter — is a scholarly act
    that belongs in the catalogue, made by a person, not a side effect of
    clicking accept on a proposal.
    """
    return []


register(
    Pipeline(
        key="W3.2",
        description="Flag charters whose text contradicts their catalogue date.",
        select=dated_charters,
        prompt=_prompt,
        parse=parse_verdict,
        materialise=materialise_verdict,
    )
)
