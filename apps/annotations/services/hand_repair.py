"""Repair graphs whose hand belongs to another manuscript part (A6).

A graph's hand must be one of its image's part's hands. The legacy import broke that for about a
thousand graphs, nearly all pointing at another part's placeholder "Main Hand". A breach is moved
only when the image's part has exactly one hand with the same name and scribe; every other breach
is listed for a person to decide, and so are attribution ticks that cross parts. A text or
editorial graph left over that way can instead have its hand cleared: those graphs need none.
Nothing here runs unless asked: `repair_graph_hands` is a dry run without `--apply`, and clears
nothing without `--clear-unmatched-text`.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import F

from apps.annotations.models import Graph

# Hand is reached through Graph's relation to it, which the boundary check declares;
# annotations does not import scribes.
Hand = Graph._meta.get_field("hand").related_model


@dataclass(frozen=True)
class GraphHandBreach:
    graph_id: int
    annotation_type: str
    image_id: int
    image_part_id: int
    hand_id: int
    hand_name: str
    hand_part_id: int
    # The hand to move to, when exactly one on the image's part shares the name and scribe.
    to_hand_id: int | None
    to_hand_name: str | None
    # The image's part's hands, as (id, name, scribe name), for a breach left to review.
    candidates: tuple[tuple[int, str, str], ...]

    @property
    def clearable(self) -> bool:
        """No hand to move to, and the graph needs none: only image graphs must carry a hand."""
        return self.to_hand_id is None and self.annotation_type != Graph.AnnotationType.IMAGE


@dataclass(frozen=True)
class CrossPartAttribution:
    hand_id: int
    hand_name: str
    hand_part_id: int
    image_id: int
    image_part_id: int


def graph_hand_breaches() -> list[GraphHandBreach]:
    """Every live graph whose hand sits on a part other than its image's, with the repair if any."""
    graphs = (
        Graph.objects.filter(hand__isnull=False)
        .exclude(hand__item_part_id=F("item_image__item_part_id"))
        .select_related("hand", "item_image")
        .order_by("item_image__item_part_id", "item_image_id", "id")
    )
    graphs = list(graphs)
    part_ids = {graph.item_image.item_part_id for graph in graphs}
    hands_by_part: dict[int, list] = {}
    for hand in Hand.objects.filter(item_part_id__in=part_ids).select_related("scribe").order_by("id"):
        hands_by_part.setdefault(hand.item_part_id, []).append(hand)

    breaches = []
    for graph in graphs:
        on_part = hands_by_part.get(graph.item_image.item_part_id, [])
        matches = [h for h in on_part if h.name == graph.hand.name and h.scribe_id == graph.hand.scribe_id]
        target = matches[0] if len(matches) == 1 else None
        breaches.append(
            GraphHandBreach(
                graph_id=graph.id,
                annotation_type=graph.annotation_type,
                image_id=graph.item_image_id,
                image_part_id=graph.item_image.item_part_id,
                hand_id=graph.hand_id,
                hand_name=graph.hand.name,
                hand_part_id=graph.hand.item_part_id,
                to_hand_id=target.id if target else None,
                to_hand_name=target.name if target else None,
                candidates=tuple((h.id, h.name, h.scribe.name) for h in on_part),
            )
        )
    return breaches


def cross_part_attributions() -> list[CrossPartAttribution]:
    """Attribution ticks (a hand marked on an image) where the image is on another part."""
    ticks = (
        Hand.item_part_images.through.objects.exclude(hand__item_part_id=F("itemimage__item_part_id"))
        .select_related("hand", "itemimage")
        .order_by("hand_id", "itemimage_id")
    )
    return [
        CrossPartAttribution(
            hand_id=tick.hand_id,
            hand_name=tick.hand.name,
            hand_part_id=tick.hand.item_part_id,
            image_id=tick.itemimage_id,
            image_part_id=tick.itemimage.item_part_id,
        )
        for tick in ticks
    ]


def apply_graph_hand_repairs(breaches: list[GraphHandBreach]) -> int:
    """Move each breach that has a repair to its hand; returns how many graphs moved.

    Each graph is saved on its own, so the edit log records the change and the search document
    follows. A graph whose hand changed since the plan was made is left alone.
    """
    moved = 0
    with transaction.atomic():
        for breach in breaches:
            if breach.to_hand_id is None:
                continue
            graph = Graph.objects.select_for_update().get(pk=breach.graph_id)
            if graph.hand_id != breach.hand_id:
                continue
            graph.hand_id = breach.to_hand_id
            graph.save(update_fields=["hand"])
            moved += 1
    return moved


def clear_unmatched_hands(breaches: list[GraphHandBreach]) -> int:
    """Clear the hand of each clearable breach; returns how many graphs lost their hand.

    This drops a link to another part's hand without making a new attribution, as a text region
    made in v3 has no hand either. Saved one by one like a move, and a graph whose hand changed
    since the plan was made is left alone.
    """
    cleared = 0
    with transaction.atomic():
        for breach in breaches:
            if not breach.clearable:
                continue
            graph = Graph.objects.select_for_update().get(pk=breach.graph_id)
            if graph.hand_id != breach.hand_id:
                continue
            graph.hand = None
            graph.save(update_fields=["hand"])
            cleared += 1
    return cleared
