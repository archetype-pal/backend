from django.db.models import Count, QuerySet
from django_filters import rest_framework as filters
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.common.viewsets import (
    FilterablePrivilegedViewSet,
    SortablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)

from .models import Hand, HandDescription, Scribe, Script
from .serializers import (
    HandDescriptionManagementSerializer,
    HandManagementSerializer,
    HandSerializer,
    ScribeManagementSerializer,
    ScribeSerializer,
    ScriptManagementSerializer,
)
from .services import optimize_scribe_public_queryset


class ScribeViewSet(ReadOnlyModelViewSet):
    # Names can repeat, so `id` breaks ties and pages never overlap.
    queryset = Scribe.objects.order_by("name", "id")
    serializer_class = ScribeSerializer

    def get_queryset(self) -> QuerySet[Scribe]:
        queryset: QuerySet[Scribe] = super().get_queryset()
        return optimize_scribe_public_queryset(queryset)


# Related rows the hand serializers read (`item_part_display` is `str(ItemPart)`, which walks
# CurrentItem → Repository or the catalogue numbers), so a list costs no per-hand queries.
_HAND_QUERYSET = Hand.objects.select_related(
    "scribe", "script", "date", "place", "item_part__current_item__repository", "item_part__historical_item"
).prefetch_related("item_part__historical_item__catalogue_numbers__catalogue", "descriptions__source")


class HandViewSet(ReadOnlyModelViewSet):
    queryset = _HAND_QUERYSET
    serializer_class = HandSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part", "item_part_images", "scribe"]


class ScribeManagementViewSet(SortablePrivilegedViewSet):
    queryset = Scribe.objects.select_related("period").annotate(hand_count=Count("hand"))
    serializer_class = ScribeManagementSerializer
    filterset_fields = ["period"]
    search_fields = ["name", "scriptorium"]
    ordering_fields = ["name", "hand_count"]


class HandManagementViewSet(SortablePrivilegedViewSet):
    queryset = _HAND_QUERYSET.prefetch_related("item_part_images")
    serializer_class = HandManagementSerializer
    filterset_fields = ["scribe", "item_part", "script", "date"]
    search_fields = ["name", "scribe__name", "script__name", "place__name"]
    ordering_fields = ["name", "scribe__name"]


class HandDescriptionManagementViewSet(FilterablePrivilegedViewSet):
    queryset = HandDescription.objects.select_related("source").all()
    serializer_class = HandDescriptionManagementSerializer
    filterset_fields = ["hand"]


class ScriptManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Script.objects.all()
    serializer_class = ScriptManagementSerializer
