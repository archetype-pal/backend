"""W2.2 — formula detection, measured against a typology that already exists.

MoA published a formulary typology — *The Standardisation of Diplomatic in
Scottish Royal Acts down to 1249*, Parts 1-2 — so this item is machine-scale
variation analysis against that work, not the discovery of it. The prompt says
so, and asks the model to name the published type where it recognises one. A
cluster matching nothing published is the interesting case, and it can only be
interesting if the recognised ones are marked.

`PUBLISHED_TYPES` is drawn from those two articles (John Reuben Davies, MoA
Feature Articles 6 and 7), in their wording where they give a name. They cover
brieves and letters; charters proper have no published type here, and a type
outside the list is dropped rather than stored as if it had been published.

**A formula is a clause from `CLAUSES`.** A cluster is keyed on its label, and a
model words a free label differently each time ("witness clause", "Witness
clause", "list of witnesses"), which leaves every cluster with one charter and
nothing to compare. A fixed list is what lets the formulary show how charters
word the same clause. It is the usual diplomatic scheme, for an expert to check.
"""

from apps.diplomatic.models import Formula, FormulaOccurrence, Proposal
from apps.diplomatic.pipelines.base import Pipeline, Unit, register
from apps.diplomatic.pipelines.extraction import transcriptions
from apps.ml.answers import parse_json

KIND_VALUES = list(Formula.Kind.values)

# Name -> how the articles identify it.
PUBLISHED_TYPES = {
    "Simple brieve": (
        "special address, then an injunction with a personal object: mando/mandamus tibi/uobis quatinus; "
        "no notification clause"
    ),
    "Brieve patent": "a brieve whose corroboration clause calls it litterae patentes: has litteras nostras patentes",
    "General brieve": (
        "a general mandate, injunction or prohibition with no personal object, addressed to a court or "
        "collectively to officers: mando et firmiter precipio quatinus"
    ),
    "General brieve to all men": (
        "the same, addressed to omnibus (probis) hominibus totius terre as well as to officers: precipio quod"
    ),
    "Letter with notification, special address": (
        "special address, a notification, then a personal instruction: sciatis me dedisse ... ideo mando vobis quatinus"
    ),
    "Letter with general notification": (
        "general address to omnibus probis hominibus, sciatis nos/quod and an operative verb, then quare (or et, "
        "unde) with an injunction or prohibition; no confirmation clause"
    ),
    "Grant of forest or warren": (
        "Alexander II's standard letter: concessimus ... in warennam/forestum; quare firmiter prohibemus ne quis ... "
        "secet aut uenetur, super nostram plenariam forisfacturam"
    ),
    "Protection against poinds": (
        "Alexander II's standard letter: ut nullus capiat namos ... pro alicuius debito uel forisfacto nisi pro "
        "eorundem proprio debito uel forisfacto"
    ),
}
TYPE_LIST = "\n".join(f"- {name}: {signs}" for name, signs in PUBLISHED_TYPES.items())

# Label -> the kind it belongs to, in the order clauses stand in a charter.
OTHER_CLAUSE = "Other clause"
CLAUSES = {
    "Invocation": Formula.Kind.OTHER,
    "Intitulatio": Formula.Kind.OTHER,
    "Address": Formula.Kind.OTHER,
    "Salutation": Formula.Kind.SALUTATION,
    "Notification": Formula.Kind.NOTIFICATION,
    "Grant": Formula.Kind.DISPOSITIVE,
    "Confirmation": Formula.Kind.DISPOSITIVE,
    "Quitclaim": Formula.Kind.DISPOSITIVE,
    "Command": Formula.Kind.DISPOSITIVE,
    "Pro salute clause": Formula.Kind.OTHER,
    "Tenure clause": Formula.Kind.OTHER,
    "Pertinents clause": Formula.Kind.OTHER,
    "Reddendo clause": Formula.Kind.OTHER,
    "Warrandice clause": Formula.Kind.OTHER,
    "Prohibition": Formula.Kind.SANCTIO,
    "Sanction": Formula.Kind.SANCTIO,
    "Corroboration": Formula.Kind.CORROBORATIO,
    "Witness clause": Formula.Kind.OTHER,
    "Dating clause": Formula.Kind.OTHER,
    "Valediction": Formula.Kind.OTHER,
    OTHER_CLAUSE: Formula.Kind.OTHER,
}
_CLAUSE_BY_LOWER = {label.lower(): label for label in CLAUSES}

SYSTEM = (
    """You are assisting a palaeography project with the diplomatic analysis of
Scottish royal charters, c. 1100-1250, in medieval Latin.

Identify the recurring formulaic clauses this charter uses — the set phrases a
chancery draws on, as distinct from the substance of the grant.

This corpus has already been studied: MoA published a formulary typology for
Scottish royal brieves and letters down to 1249. Where a clause belongs to one
of these types, give its name exactly as written here in `published_type`:

"""
    + TYPE_LIST
    + """

Where it does not, leave that empty. Formulae of charters proper have no type in
this list. An unrecognised formula is a finding, and marking it as recognised
would bury it.

Return JSON only, no prose:

{"formulae": [{"clause": "<clause>", "excerpt": "<the words from this charter, verbatim>",
               "published_type": "<the published type, or empty>"}]}

Clauses, name each exactly as written here: """
    + ", ".join(CLAUSES)
    + f"""

Use {OTHER_CLAUSE} for a set phrase none of these fits. Quote the excerpt exactly as
the charter has it, including Latin case. Leave out what is not a formula."""
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
        excerpt = str(item.get("excerpt", "")).strip()
        if not excerpt:
            continue
        label = _CLAUSE_BY_LOWER.get(str(item.get("clause", "")).strip().lower(), OTHER_CLAUSE)
        published = str(item.get("published_type", "")).strip()
        cleaned.append(
            {
                "kind": str(CLAUSES[label]),
                "label": label,
                "excerpt": excerpt,
                "published_type": published if published in PUBLISHED_TYPES else "",
            }
        )
    return {"formulae": cleaned}


def materialise_formulae(proposal: Proposal, *, reviewer) -> list[FormulaOccurrence]:
    """Attach this charter to each formula, creating the cluster if it is new.

    The cluster is keyed on (kind, label) rather than on the excerpt, because
    two charters using the same formula word it differently — which is the
    variation the item exists to measure. `published_type` follows the first
    occurrence, so a cluster gains a type when a later charter supplies one.
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
        if item.get("published_type") and not formula.published_type:
            formula.published_type = item["published_type"]
            formula.save(update_fields=["published_type"])
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
        worth_reviewing=lambda payload: bool(payload["formulae"]),
        items_key="formulae",
    )
)
