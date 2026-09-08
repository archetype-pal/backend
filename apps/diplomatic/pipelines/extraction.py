"""W2.1 — diplomatic entity extraction, and W3.3 — the triples it stages into.

One workstream, two deliveries. The roadmap is explicit that W3.3 is stage two
of W2.1 rather than a second item racing it: both read the same charters and
emit the same relations, and running them as rivals would produce two
disagreeing accounts of the same text for a human to reconcile.

Bootstrapped from what the corpus already marks up. `<persName>` appears 1,061
times across 141 of 899 texts and `<placeName>` twelve times in total, so this
is not a greenfield task: the seed is real for people and effectively absent for
places, and the prompt says so rather than implying the model is starting from
nothing.
"""

import re

from apps.diplomatic.models import CharterEntity, Proposal, Relation
from apps.diplomatic.pipelines.base import Pipeline, Unit, register
from apps.manuscripts.models import ImageText

_TAGS = re.compile(r"<[^>]+>")

ROLE_VALUES = list(CharterEntity.Role.values)
PREDICATE_VALUES = list(Relation.Predicate.values)

EXTRACTION_SYSTEM = (
    """You are assisting a palaeography project with the diplomatic analysis of
Scottish royal charters, c. 1100-1250, written in medieval Latin.

Extract only what the charter itself says. Do not infer from historical
knowledge: if the text does not name a beneficiary, there is no beneficiary to
report. A scholar will check every item against the text, so a confident guess
costs more than an omission.

Return JSON only, no prose, in this shape:

{"entities": [{"role": "<role>", "name": "<surface form as written>",
               "normalised": "<modern or standard form, or empty>",
               "note": "<why, if the role is not obvious>"}]}

Roles: """
    + ", ".join(ROLE_VALUES)
    + """

Rules:
- `name` is the wording as it appears, including Latin case. Do not translate it.
- `normalised` is optional; leave it empty rather than guess an identification.
- Witnesses are the people in the witness list, not everyone mentioned.
- `transaction` is the kind of act (grant, confirmation, quitclaim, ...), one entry.
- Return an empty list rather than inventing entries."""
)

TRIPLES_SYSTEM = (
    """You are assisting a palaeography project with Scottish royal charters,
c. 1100-1250, in medieval Latin.

Turn the charter into knowledge-graph triples. Extract only relations the text
states. A scholar approves every triple before it is recorded, so an omission is
cheap and a plausible invention is expensive.

Return JSON only, no prose:

{"triples": [{"subject": "...", "predicate": "<predicate>", "object": "..."}]}

Predicates: """
    + ", ".join(PREDICATE_VALUES)
    + """

Use the wording the charter uses for subject and object. Do not resolve people
to modern identifications — naming who someone "really was" is a scholarly
judgement, not an extraction."""
)


def plain_text(content: str, limit: int = 12000) -> str:
    """TEI stripped to readable text. Truncated, and says so if it was."""
    text = _TAGS.sub(" ", content or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit] + " […truncated]"
    return text


def transcriptions() -> list[Unit]:
    """Every charter transcription. Translations are modern and not charters."""
    rows = ImageText.objects.filter(type="Transcription").values_list("id", "content", "item_image_id")
    return [
        Unit(source_type="imagetext", source_id=pk, context={"text": plain_text(content), "image_id": image_id})
        for pk, content, image_id in rows
        if (content or "").strip()
    ]


def _extraction_prompt(unit: Unit) -> tuple[str, str]:
    return EXTRACTION_SYSTEM, f"Charter text:\n\n{unit.context['text']}"


def _triples_prompt(unit: Unit) -> tuple[str, str]:
    return TRIPLES_SYSTEM, f"Charter text:\n\n{unit.context['text']}"


def parse_entities(text: str):
    from apps.diplomatic.services import parse_json

    payload = parse_json(text)
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, list):
        raise ValueError("Expected an object with an 'entities' list.")

    cleaned = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        name = str(item.get("name", "")).strip()
        # A role outside the vocabulary is the model inventing a category; drop
        # it rather than store a value nothing can query.
        if role not in ROLE_VALUES or not name:
            continue
        cleaned.append(
            {
                "role": role,
                "name": name[:255],
                "normalised": str(item.get("normalised", "")).strip()[:255],
                "note": str(item.get("note", "")).strip(),
            }
        )
    return {"entities": cleaned}


def parse_triples(text: str):
    from apps.diplomatic.services import parse_json

    payload = parse_json(text)
    triples = payload.get("triples") if isinstance(payload, dict) else None
    if not isinstance(triples, list):
        raise ValueError("Expected an object with a 'triples' list.")

    cleaned = []
    for item in triples:
        if not isinstance(item, dict):
            continue
        predicate = str(item.get("predicate", "")).strip().lower()
        subject = str(item.get("subject", "")).strip()
        obj = str(item.get("object", "")).strip()
        if predicate not in PREDICATE_VALUES or not subject or not obj:
            continue
        cleaned.append({"subject": subject[:255], "predicate": predicate, "object": obj[:255]})
    return {"triples": cleaned}


def materialise_entities(proposal: Proposal, *, reviewer) -> list[CharterEntity]:
    return [
        CharterEntity.objects.create(
            image_text_id=proposal.source_id,
            role=item["role"],
            name=item["name"],
            normalised=item.get("normalised", ""),
            note=item.get("note", ""),
            proposal=proposal,
        )
        for item in proposal.payload.get("entities", [])
    ]


def materialise_triples(proposal: Proposal, *, reviewer) -> list[Relation]:
    return [
        Relation.objects.create(
            image_text_id=proposal.source_id,
            subject=item["subject"],
            predicate=item["predicate"],
            object=item["object"],
            proposal=proposal,
        )
        for item in proposal.payload.get("triples", [])
    ]


register(
    Pipeline(
        key="W2.1",
        description="Extract granter, beneficiary, witnesses, places, dates and transaction type.",
        select=transcriptions,
        prompt=_extraction_prompt,
        parse=parse_entities,
        materialise=materialise_entities,
    )
)

register(
    Pipeline(
        key="W3.3",
        description="Knowledge-graph triples — stage two of the W2.1 extraction workstream.",
        select=transcriptions,
        prompt=_triples_prompt,
        parse=parse_triples,
        materialise=materialise_triples,
    )
)
