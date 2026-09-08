"""The agent's tool surface — an explicit allow-list, read-only by construction.

Every tool here reads. None writes, and none can: there is no path from this
module to a save, and the review gate in `apps.diplomatic` exists precisely so
that "the agent proposes" and "the agent writes" stay different things.

Availability is computed, not asserted. `compare_hands` is registered and
permanently unavailable because W1.2/W1.3 have not been built; `fetch_witnesses`
is available exactly when an expert has approved some witnesses. An agent is
never offered a tool that would answer with nothing, and the reason a tool is
missing is a string an operator can read rather than an absence they must infer.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
import re
from typing import Any

from apps.annotations.models import Graph
from apps.diplomatic.models import CharterEntity, Relation
from apps.manuscripts.models import ImageText, ItemImage
from apps.manuscripts.services.regions import heights_for, region_for

# Bounds every tool result. A tool that can return the corpus can spend a
# context window on one call, and a model that has read 900 charters at once has
# not searched anything.
MAX_RESULTS = 25
SNIPPET = 400

_REGION = re.compile(r"^\d+,\d+,\d+,\d+$")


class ToolError(Exception):
    """A tool refused or could not run. Reported to the model, not raised out."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # JSON Schema for the arguments, in the shape the providers expect.
    parameters: dict[str, Any]
    run: Callable[..., Any]
    # Why this tool is not offered, when it is not. Empty means it is.
    unavailable: Callable[[], str] = field(default=lambda: "")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


TOOL_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    TOOL_REGISTRY[tool.name] = tool
    return tool


def _plain(content: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content or "")).strip()


def _visible() -> Any:
    """Public statuses only. An agent must not quote an unpublished draft."""
    return ImageText.objects.filter(status__in=[ImageText.Status.LIVE, ImageText.Status.REVIEWED])


def _describe(text: ImageText) -> dict[str, Any]:
    image = text.item_image
    part = image.item_part
    item = part.historical_item
    current = part.current_item
    return {
        "image_text_id": text.pk,
        "type": text.type,
        "item_image_id": image.pk,
        "item_part_id": part.pk,
        "historical_item_id": item.pk if item else None,
        "locus": image.locus,
        "shelfmark": current.shelfmark if current else "",
        "repository": current.repository.name if current and current.repository_id else "",
        "date": item.date.date if item and item.date_id else "",
    }


# --- search_charters ---------------------------------------------------------


def search_charters(query: str, limit: int = 10) -> dict[str, Any]:
    """Substring search over published charter texts.

    Deliberately the database and not Meilisearch: the search index carries
    catalogue metadata for the faceted browse, and the agent needs the words of
    the charter. Slower, and correct.
    """
    query = (query or "").strip()
    if len(query) < 3:
        raise ToolError("A search needs at least three characters.")

    rows = (
        _visible()
        .filter(content__icontains=query)
        .select_related(
            "item_image__item_part__current_item__repository",
            "item_image__item_part__historical_item__date",
        )[: min(int(limit or 10), MAX_RESULTS)]
    )

    results = []
    for text in rows:
        plain = _plain(text.content)
        position = plain.lower().find(query.lower())
        start = max(0, position - SNIPPET // 2)
        entry = _describe(text)
        entry["snippet"] = plain[start : start + SNIPPET]
        results.append(entry)
    return {"query": query, "count": len(results), "results": results}


register(
    Tool(
        name="search_charters",
        description=(
            "Find published charters whose transcription or translation contains a phrase. "
            "Returns identifiers, shelfmark, folio and a snippet. Search the Latin for a Latin "
            "phrase; the translations are English."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The phrase to look for."},
                "limit": {"type": "integer", "description": f"Maximum results, up to {MAX_RESULTS}."},
            },
            "required": ["query"],
        },
        run=search_charters,
    )
)


# --- get_charter -------------------------------------------------------------


def get_charter(image_text_id: int) -> dict[str, Any]:
    try:
        text = (
            _visible()
            .select_related(
                "item_image__item_part__current_item__repository",
                "item_image__item_part__historical_item__date",
            )
            .get(pk=int(image_text_id))
        )
    except (ImageText.DoesNotExist, TypeError, ValueError):  # fmt: skip
        raise ToolError(f"No published charter text with id {image_text_id}.") from None

    entry = _describe(text)
    entry["text"] = _plain(text.content)[:20000]
    entry["other_texts"] = [
        {"image_text_id": other.pk, "type": other.type}
        for other in _visible().filter(item_image_id=text.item_image_id).exclude(pk=text.pk)
    ]
    return entry


register(
    Tool(
        name="get_charter",
        description="Read one charter text in full, with its shelfmark, folio and date.",
        parameters={
            "type": "object",
            "properties": {"image_text_id": {"type": "integer"}},
            "required": ["image_text_id"],
        },
        run=get_charter,
    )
)


# --- get_image_regions -------------------------------------------------------


def get_image_regions(item_image_id: int, allograph: str = "", limit: int = 10) -> dict[str, Any]:
    """Annotated regions on one folio — the anchors a citation points at."""
    try:
        image = ItemImage.objects.select_related(
            "item_part__current_item__repository", "item_part__historical_item__date"
        ).get(pk=int(item_image_id))
    except (ItemImage.DoesNotExist, TypeError, ValueError):  # fmt: skip
        raise ToolError(f"No image with id {item_image_id}.") from None

    graphs = Graph.objects.filter(item_image_id=image.pk).select_related("allograph", "hand")
    if allograph:
        graphs = graphs.filter(allograph__name__iexact=allograph)
    graphs = list(graphs[: min(int(limit or 10), MAX_RESULTS)])

    heights, unresolved = heights_for({image.pk})
    regions = []
    for graph in graphs:
        region = region_for(graph.annotation, image.pk, heights)
        if region is None:
            # Dropped rather than guessed: the height is unknown, and a mirrored
            # box is a citation that points confidently at the wrong place.
            continue
        regions.append(
            {
                "graph_id": graph.pk,
                "region": region,
                "allograph": graph.allograph.name if graph.allograph_id else "",
                "hand_id": graph.hand_id,
                "item_image_id": image.pk,
            }
        )

    return {
        "item_image_id": image.pk,
        "locus": image.locus,
        "count": len(regions),
        "regions": regions,
        "note": (
            "Image dimensions could not be resolved, so no region is citable for this folio." if unresolved else ""
        ),
    }


register(
    Tool(
        name="get_image_regions",
        description=(
            "List annotated regions on a folio as IIIF 'x,y,w,h' strings, for citing a claim to a "
            "specific place on the page. Optionally filtered to one allograph."
        ),
        parameters={
            "type": "object",
            "properties": {
                "item_image_id": {"type": "integer"},
                "allograph": {"type": "string", "description": "e.g. 'a' or 'long-s'."},
                "limit": {"type": "integer"},
            },
            "required": ["item_image_id"],
        },
        run=get_image_regions,
    )
)


# --- fetch_witnesses ---------------------------------------------------------


def fetch_witnesses(name: str = "", image_text_id: int = 0, limit: int = 25) -> dict[str, Any]:
    entities = CharterEntity.objects.filter(role=CharterEntity.Role.WITNESS)
    if name:
        entities = entities.filter(name__icontains=name)
    if image_text_id:
        entities = entities.filter(image_text_id=int(image_text_id))
    rows = [
        {"name": entity.name, "normalised": entity.normalised, "image_text_id": entity.image_text_id}
        for entity in entities[: min(int(limit or 25), MAX_RESULTS)]
    ]
    return {"count": len(rows), "witnesses": rows}


def _witnesses_unavailable() -> str:
    if CharterEntity.objects.filter(role=CharterEntity.Role.WITNESS).exists():
        return ""
    return "No witness has been extracted and approved yet (W2.1 has not been run and reviewed)."


register(
    Tool(
        name="fetch_witnesses",
        description="Look up witnesses a scholar has approved, by name or by charter.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "image_text_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
        },
        run=fetch_witnesses,
        unavailable=_witnesses_unavailable,
    )
)


# --- fetch_relations ---------------------------------------------------------


def fetch_relations(predicate: str = "", subject: str = "", limit: int = 25) -> dict[str, Any]:
    relations = Relation.objects.all()
    if predicate:
        relations = relations.filter(predicate=predicate)
    if subject:
        relations = relations.filter(subject__icontains=subject)
    rows = [
        {
            "subject": relation.subject,
            "predicate": relation.predicate,
            "object": relation.object,
            "image_text_id": relation.image_text_id,
        }
        for relation in relations[: min(int(limit or 25), MAX_RESULTS)]
    ]
    return {"count": len(rows), "relations": rows}


def _relations_unavailable() -> str:
    if Relation.objects.exists():
        return ""
    return "No relation has been approved yet (W3.3 has not been run and reviewed)."


register(
    Tool(
        name="fetch_relations",
        description=(
            "Query approved knowledge-graph triples: granted_by, witnessed_by, written_by, beneficiary_of, located_at."
        ),
        parameters={
            "type": "object",
            "properties": {
                "predicate": {"type": "string"},
                "subject": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        run=fetch_relations,
        unavailable=_relations_unavailable,
    )
)


# --- cite_record -------------------------------------------------------------


def cite_record(claim: str, image_text_id: int, item_image_id: int = 0, region: str = "") -> dict[str, Any]:
    """Verify an anchor before it is allowed into an answer.

    This is where §8.3 is enforced rather than hoped for. The model does not get
    to assert a citation; it submits one, and this resolves it against the
    record. A charter id that does not exist, or a region on the wrong folio,
    comes back as an error the model can see and correct — which is the whole
    difference between a clickable anchor and a correct one.
    """
    claim = (claim or "").strip()
    if not claim:
        raise ToolError("A citation needs the claim it supports.")

    try:
        text = _visible().select_related("item_image__item_part__current_item__repository").get(pk=int(image_text_id))
    except (ImageText.DoesNotExist, TypeError, ValueError):  # fmt: skip
        raise ToolError(f"Cannot cite {image_text_id}: no such published charter text.") from None

    anchor = _describe(text)
    anchor["claim"] = claim[:1000]

    if item_image_id and int(item_image_id) != text.item_image_id:
        raise ToolError(
            f"Image {item_image_id} does not carry text {image_text_id}; that citation points at the wrong folio."
        )

    if region:
        if not _REGION.match(region.strip()):
            raise ToolError("A region must be four integers, 'x,y,w,h'.")
        anchor["region"] = region.strip()
        anchor["verified_region"] = False
        # A region is accepted as an anchor but never certified here: only a
        # region this platform computed from a stored annotation is known to be
        # right, and the model may have arrived at one by arithmetic.
        for graph_region in _regions_on(text.item_image_id):
            if graph_region == region.strip():
                anchor["verified_region"] = True
                break

    return {"cited": anchor}


def _regions_on(item_image_id: int) -> list[str]:
    heights, _ = heights_for({item_image_id})
    regions = []
    for graph in Graph.objects.filter(item_image_id=item_image_id).only("id", "annotation"):
        region = region_for(graph.annotation, item_image_id, heights)
        if region:
            regions.append(region)
    return regions


register(
    Tool(
        name="cite_record",
        description=(
            "Register one claim and the record that supports it. Every assertion in the final "
            "answer must be cited this way first; an anchor that does not resolve is refused, so "
            "call this before writing the claim down."
        ),
        parameters={
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "The assertion this record supports."},
                "image_text_id": {"type": "integer"},
                "item_image_id": {"type": "integer", "description": "Optional; checked against the text."},
                "region": {"type": "string", "description": "Optional IIIF region 'x,y,w,h'."},
            },
            "required": ["claim", "image_text_id"],
        },
        run=cite_record,
    )
)


# --- compare_hands -----------------------------------------------------------


def compare_hands(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise ToolError("Hand comparison is not built.")


register(
    Tool(
        name="compare_hands",
        description="Judge whether two charters share a scribal hand.",
        parameters={
            "type": "object",
            "properties": {"left_image_text_id": {"type": "integer"}, "right_image_text_id": {"type": "integer"}},
            "required": ["left_image_text_id", "right_image_text_id"],
        },
        run=compare_hands,
        # Registered but never offered. Named here so the allow-list can hold it
        # from the start, and so the reason it is missing is a sentence rather
        # than a silence: the roadmap's worked example needs this tool, and it
        # needs an encoder the programme has not trained.
        unavailable=lambda: "Hand comparison needs the palaeographic encoder (W1.2/W1.3), which is not built.",
    )
)


def available_for(identity: Any) -> list[Tool]:
    """Tools this identity may call *and* that can currently answer."""
    return [tool for name, tool in sorted(TOOL_REGISTRY.items()) if identity.may_call(name) and not tool.unavailable()]


def invoke(identity: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Call one tool, enforcing the allow-list at the credential.

    The check is here and not in the prompt because a prompt is a request and
    this is a rule. A model that invents a tool name, or remembers one from a
    previous identity, gets a refusal.
    """
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        raise ToolError(f"No such tool '{name}'.")
    if not identity.may_call(name):
        raise ToolError(f"Identity '{identity.slug}' is not permitted to call '{name}'.")
    reason = tool.unavailable()
    if reason:
        raise ToolError(reason)
    if not isinstance(arguments, dict):
        raise ToolError("Tool arguments must be an object.")

    allowed = set(tool.parameters.get("properties", {}))
    unexpected = set(arguments) - allowed
    if unexpected:
        raise ToolError(f"Unexpected arguments for '{name}': {sorted(unexpected)}.")
    return tool.run(**arguments)
