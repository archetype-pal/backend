"""W2.2 — formula detection, measured against a typology that already exists.

MoA published a formulary typology — *The Standardisation of Diplomatic in
Scottish Royal Acts down to 1249*, Parts 1-2 — so this item is machine-scale
variation analysis against that work, not the discovery of it. The prompt says
so, and asks the model to name the published type where it recognises one. A
cluster matching nothing published is the interesting case, and it can only be
interesting if the recognised ones are marked.
"""

from apps.diplomatic.models import Formula, FormulaOccurrence, Proposal
from apps.diplomatic.pipelines.base import Pipeline, Unit, register
from apps.diplomatic.pipelines.extraction import transcriptions
from apps.ml.answers import parse_json

KIND_VALUES = list(Formula.Kind.values)

SYSTEM = (
    """You are assisting a palaeography project with the diplomatic analysis of
Scottish royal charters, c. 1100-1250, in medieval Latin.

Identify the recurring formulaic clauses this charter uses — the set phrases a
chancery draws on, as distinct from the substance of the grant.

This corpus has already been studied: MoA published a formulary typology for
Scottish royal acts down to 1249. Where a clause corresponds to a recognised
type, name it in `published_type`. Where it does not, leave that empty — an
unrecognised formula is a finding, and marking it as recognised would bury it.

Return JSON only, no prose:

{"formulae": [{"kind": "<kind>", "label": "<short name>",
               "excerpt": "<the words from this charter, verbatim>",
               "published_type": "<the published type, or empty>"}]}

Kinds: """
    + ", ".join(KIND_VALUES)
    + """

Quote the excerpt exactly as the charter has it, including Latin case. Return an
empty list rather than forcing a clause into a kind it does not fit."""
)


def _prompt(unit: Unit) -> tuple[str, str]:
    return SYSTEM, f"Charter text:\n\n{unit.context['text']}"


def parse_formulae(text: str):
    payload = parse_json(text)
    found = payload.get("formulae") if isinstance(payload, dict) else None
    if not isinstance(found, list):
        raise ValueError("Expected an object with a 'formulae' list.")

    cleaned = []
    for item in found:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip().lower()
        label = str(item.get("label", "")).strip()
        if kind not in KIND_VALUES or not label:
            continue
        cleaned.append(
            {
                "kind": kind,
                "label": label[:255],
                "excerpt": str(item.get("excerpt", "")).strip(),
                "published_type": str(item.get("published_type", "")).strip()[:255],
            }
        )
    return {"formulae": cleaned}


def materialise_formulae(proposal: Proposal, *, reviewer) -> list[FormulaOccurrence]:
    """Attach this charter to each formula, creating the cluster if it is new.

    The cluster is keyed on (kind, label) rather than on the excerpt, because
    two charters using the same formula word it differently — which is the
    variation the item exists to measure.
    """
    created = []
    for item in proposal.payload.get("formulae", []):
        formula, _ = Formula.objects.get_or_create(
            kind=item["kind"],
            label=item["label"],
            defaults={
                "exemplar": item.get("excerpt", ""),
                "published_type": item.get("published_type", ""),
                "proposal": proposal,
            },
        )
        occurrence, made = FormulaOccurrence.objects.get_or_create(
            formula=formula,
            image_text_id=proposal.source_id,
            defaults={"excerpt": item.get("excerpt", "")},
        )
        if made:
            created.append(occurrence)
    return created


register(
    Pipeline(
        key="W2.2",
        description="Detect recurring diplomatic formulae, against MoA's published typology.",
        select=transcriptions,
        prompt=_prompt,
        parse=parse_formulae,
        materialise=materialise_formulae,
    )
)
