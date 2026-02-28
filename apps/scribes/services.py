"""Application services for scribes app workflows."""

from typing import Any

from django.db.models import QuerySet

from apps.manuscripts.models import ItemImage
from apps.scribes.models import Scribe
from apps.symbols_structure.models import Allograph


def get_hand_item_images_payload(item_part_id: str | None) -> dict[str, list[dict[str, Any]]]:
    images = ItemImage.objects.filter(item_part_id=item_part_id).only("id", "locus")
    return {"images": [{"id": img.id, "text": str(img)} for img in images]}


def optimize_scribe_public_queryset(queryset: QuerySet[Scribe]) -> QuerySet[Scribe]:
    """Prefetch graph/allograph data so idiograph extraction stays query-free."""
    return queryset.prefetch_related("hand_set__graph_set__allograph__character")


def get_scribe_idiographs(scribe: Scribe) -> list[Allograph]:
    """Return distinct idiographs for a scribe, preferring prefetched graph data."""
    idiographs_by_id: dict[int, Allograph] = {}
    hands = scribe.hand_set.all()
    for hand in hands:
        for graph in hand.graph_set.all():
            allograph = graph.allograph
            idiographs_by_id[allograph.id] = allograph

    if idiographs_by_id:
        return sorted(idiographs_by_id.values(), key=lambda allograph: allograph.name.lower())

    return list(Allograph.objects.filter(graph__hand__scribe=scribe).distinct().select_related("character"))
