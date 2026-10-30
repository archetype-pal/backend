"""Application services for scribes app workflows."""

from django.db.models import QuerySet

from apps.scribes.models import Scribe
from apps.symbols_structure.models import Allograph


def optimize_scribe_public_queryset(queryset: QuerySet[Scribe]) -> QuerySet[Scribe]:
    """Prefetch graph/allograph data so idiograph extraction stays query-free."""
    return queryset.select_related("period").prefetch_related("hand_set__graph_set__allograph__character")


def get_scribe_idiographs(scribe: Scribe) -> list[Allograph]:
    """Return a scribe's distinct idiographs, read from its hands' graphs.

    The graph manager hides trashed graphs, so prefetched and unprefetched
    reads agree; with `optimize_scribe_public_queryset` this costs no query.
    """
    idiographs_by_id: dict[int, Allograph] = {}
    for hand in scribe.hand_set.all():
        for graph in hand.graph_set.all():
            idiographs_by_id[graph.allograph.id] = graph.allograph
    return sorted(idiographs_by_id.values(), key=lambda allograph: allograph.name.lower())
