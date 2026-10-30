"""Editorial workflows over `ImageText`: status transitions, text↔region links, HTR import, export.

Views validate input and map these results onto HTTP; everything that writes
rows lives here, inside the transaction and audit scope it needs.
"""

from collections.abc import Iterable
from typing import Any
from xml.etree.ElementTree import ParseError

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.db.models.functions import Length
from rest_framework.exceptions import NotFound

from apps.annotations.models import Graph
from apps.common.audit import audit_actor
from apps.common.exceptions import BadRequest, Conflict
from apps.manuscripts.models import ImageText, ItemImage, StatusTransition
from apps.manuscripts.services.htr import alto_to_lines, lines_to_tei, page_xml_to_lines
from apps.manuscripts.services.tei import add_graph_ref, remove_graph_ref, remove_graph_ref_at

# --- the sole text of a kind ---------------------------------------------------


def upsert_sole_text(*, item_image_id: int, type_value: str, defaults: dict[str, Any], actor) -> ImageText:
    """Create or update the one `ImageText` of `type_value` on an image, under `actor`'s audit scope.

    The (item_image, type) uniqueness invariant means there is at most one
    row, so a caller need not know its id. Unknown image: `NotFound`.
    """
    if not ItemImage.objects.filter(pk=item_image_id).exists():
        raise NotFound("Unknown item_image.")
    with audit_actor(actor):
        row: ImageText
        row, _ = ImageText.objects.update_or_create(item_image_id=item_image_id, type=type_value, defaults=defaults)
    return row


# --- status workflow -----------------------------------------------------------


def transition_texts(
    texts: Iterable[ImageText],
    *,
    to_status: str,
    actor,
    note: str = "",
    assignee_id: int | None = None,
) -> int:
    """Move every text to `to_status`, writing one `StatusTransition` per row.

    A reviewer can be nominated when sending to Review; the nomination is
    cleared whenever a row leaves Review. Returns the number of rows moved.
    """
    with transaction.atomic(), audit_actor(actor):
        transitions = []
        count = 0
        for text in texts:
            from_status = text.status
            text.status = to_status
            if to_status == ImageText.Status.REVIEW and assignee_id:
                text.review_assignee_id = assignee_id
            elif to_status != ImageText.Status.REVIEW:
                text.review_assignee = None
            text.save(update_fields=["status", "review_assignee", "modified"])
            transitions.append(
                StatusTransition(image_text=text, actor=actor, from_status=from_status, to_status=to_status, note=note)
            )
            count += 1
        StatusTransition.objects.bulk_create(transitions)
    return count


def set_language(texts: Iterable[ImageText], *, language: str, actor) -> int:
    """Per-row save, not `update()`: the search sync and the audit log hang off post_save."""
    with transaction.atomic(), audit_actor(actor):
        count = 0
        for text in texts:
            text.language = language
            text.save(update_fields=["language", "modified"])
            count += 1
    return count


def delete_texts(queryset: QuerySet[ImageText], *, actor) -> int:
    """Hard-delete; returns only the ImageText rows removed, not the cascaded StatusTransitions."""
    with audit_actor(actor):
        _total, by_model = queryset.delete()
    return int(by_model.get(ImageText._meta.label, 0))


# --- text <-> region links -------------------------------------------------------


def strip_region_refs(item_image_id: int, graph_id: int) -> None:
    """Remove every `corresp`/`data-graph-id` reference to `graph_id` from the image's texts."""
    for text in ImageText.objects.filter(item_image_id=item_image_id):
        updated = remove_graph_ref(text.content or "", graph_id)
        if updated != (text.content or ""):
            text.content = updated
            text.save(update_fields=["content", "modified"])


def link_region(
    text: ImageText, *, element_index: int, actor, geometry: dict | None = None, graph_id: int | None = None
) -> tuple[Graph, bool]:
    """Link the `element_index`-th linkable element of `text` to a region.

    With `geometry`, a new TEXT graph is created; with `graph_id`, an existing
    TEXT graph of the same image is reused (a trashed one is restored, so a
    link left dangling by a trash can be repaired). Returns `(graph, created)`.
    """
    graph = None
    if graph_id is not None:
        graph = Graph.all_objects.filter(id=graph_id, annotation_type="text", item_image_id=text.item_image_id).first()
        if graph is None:
            raise BadRequest("No text region with that graph_id on this image.")

    try:
        with transaction.atomic(), audit_actor(actor):
            if graph is None:
                graph = Graph.objects.create(
                    item_image_id=text.item_image_id, annotation=geometry, annotation_type="text"
                )
            elif graph.deleted_at is not None:
                graph.restore()
            text.content = add_graph_ref(text.content or "", element_index, graph.id)
            text.save(update_fields=["content", "modified"])
    except IndexError:
        raise BadRequest(f"No linkable element at index {element_index}.") from None
    return graph, graph_id is None


def unlink_region(text: ImageText, *, graph_id: int, actor) -> None:
    """Delete the region graph and strip its reference from every text of the image.

    A real delete, not a trash, and it reaches trashed rows too: the refs are
    gone by the time it runs, so leaving the row behind would make it an
    unreachable orphan on restore.
    """
    with transaction.atomic(), audit_actor(actor):
        strip_region_refs(text.item_image_id, graph_id)
        Graph.all_objects.filter(id=graph_id, annotation_type="text", item_image_id=text.item_image_id).delete()
    text.refresh_from_db()


def unlink_element(text: ImageText, *, element_index: int, graph_id: int, actor) -> None:
    """Strip `graph_id` from one element of `text` only; the graph and other links stay."""
    try:
        with transaction.atomic(), audit_actor(actor):
            updated = remove_graph_ref_at(text.content or "", element_index, graph_id)
            if updated != (text.content or ""):
                text.content = updated
                text.save(update_fields=["content", "modified"])
    except IndexError:
        raise BadRequest(f"No linkable element at index {element_index}.") from None


# --- HTR import -------------------------------------------------------------------


def import_htr(*, item_image_id: int, fmt: str, xml: str, kind: str, language: str, actor) -> dict[str, int]:
    """Create a Draft text from PAGE-XML / ALTO output, one TEXT graph per line with a polygon.

    Returns `{"id", "lines", "regions"}`.
    """
    try:
        lines = page_xml_to_lines(xml) if fmt == "page" else alto_to_lines(xml)
    except ParseError:
        raise BadRequest("Malformed XML.") from None
    if not lines:
        raise BadRequest("No text lines found in the document.")
    if not ItemImage.objects.filter(pk=item_image_id).exists():
        raise NotFound("Unknown item_image.")
    conflict = Conflict(f"A {kind} already exists for this image.")
    if ImageText.objects.filter(item_image_id=item_image_id, type=kind).exists():
        raise conflict

    try:
        with transaction.atomic(), audit_actor(actor):
            graph_ids: list[int | None] = []
            for line in lines:
                geom = line.geojson()
                if geom is None:
                    graph_ids.append(None)
                    continue
                graph = Graph.objects.create(item_image_id=item_image_id, annotation=geom, annotation_type="text")
                graph_ids.append(graph.id)
            image_text = ImageText.objects.create(
                item_image_id=item_image_id,
                content=lines_to_tei(lines, graph_ids=graph_ids),
                type=kind,
                status=ImageText.Status.DRAFT,
                language=language,
            )
    except IntegrityError:
        # The pre-check races with concurrent writes; the (item_image, type)
        # unique constraint is the real guard.
        raise conflict from None
    return {"id": image_text.id, "lines": len(lines), "regions": sum(1 for g in graph_ids if g)}


# --- export -----------------------------------------------------------------------

EXPORT_COLUMNS = [
    "id",
    "item_image_id",
    "item_part_id",
    "locus",
    "type",
    "status",
    "language",
    "review_assignee_username",
    "char_count",
    "is_empty",
    "created",
    "modified",
]


def export_rows(queryset: QuerySet[ImageText]) -> list[dict[str, Any]]:
    """Triage rows for every text in `queryset` — metadata and a character count, never the content."""
    rows = queryset.annotate(char_count=Length("content")).values(
        "id",
        "item_image_id",
        "item_image__item_part_id",
        "item_image__locus",
        "type",
        "status",
        "language",
        "review_assignee__username",
        "char_count",
        "created",
        "modified",
    )
    return [
        {
            "id": r["id"],
            "item_image_id": r["item_image_id"],
            "item_part_id": r["item_image__item_part_id"],
            "locus": r["item_image__locus"] or "",
            "type": r["type"],
            "status": r["status"],
            "language": r["language"],
            "review_assignee_username": r["review_assignee__username"],
            "char_count": r["char_count"] or 0,
            "is_empty": not r["char_count"],
            "created": r["created"].isoformat(),
            "modified": r["modified"].isoformat(),
        }
        for r in rows
    ]
