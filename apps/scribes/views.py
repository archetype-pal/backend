from django.db.models import Count, QuerySet
from django_filters import rest_framework as filters
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.common.viewsets import (
    ManagementViewSet,
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
    # Leaves out DigiPal's placeholder (`Scribe.is_placeholder`), so its page is a 404.
    queryset = Scribe.objects.filter(pk__gte=1).order_by("name")
    serializer_class = ScribeSerializer

    def get_queryset(self) -> QuerySet[Scribe]:
        queryset: QuerySet[Scribe] = super().get_queryset()
        return optimize_scribe_public_queryset(queryset)


# Related rows the hand serializers read (`item_part_display` is `str(ItemPart)`, which walks
# CurrentItem → Repository or the catalogue numbers), so a list costs no per-hand queries.
_HAND_QUERYSET = Hand.objects.select_related(
    "scribe__scriptorium",
    "script",
    "date",
    "place",
    "item_part__current_item__repository",
    "item_part__historical_item",
).prefetch_related("item_part__historical_item__catalogue_numbers__catalogue", "descriptions__source")


class HandFilter(filters.FilterSet):
    # Like `ScribeViewSet`: the placeholder is not a scribe to filter by.
    scribe = filters.ModelChoiceFilter(queryset=Scribe.objects.filter(pk__gte=1))

    class Meta:
        model = Hand
        fields = ["item_part", "item_part_images", "scribe"]


class HandViewSet(ReadOnlyModelViewSet):
    queryset = _HAND_QUERYSET
    serializer_class = HandSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = HandFilter


class ScribeManagementViewSet(ManagementViewSet):
    queryset = Scribe.objects.select_related("period", "scriptorium").annotate(hand_count=Count("hand"))
    serializer_class = ScribeManagementSerializer
    filterset_fields = ["period"]
    search_fields = ["name", "scriptorium__name"]
    ordering_fields = ["name", "hand_count"]


class HandManagementViewSet(ManagementViewSet):
    queryset = _HAND_QUERYSET.prefetch_related("item_part_images")
    serializer_class = HandManagementSerializer
    filterset_fields = ["scribe", "item_part", "script", "date"]
    search_fields = ["name", "scribe__name", "script__name", "place__name"]
    ordering_fields = ["name", "scribe__name"]


class HandDescriptionManagementViewSet(ManagementViewSet):
    queryset = HandDescription.objects.select_related("source")
    serializer_class = HandDescriptionManagementSerializer
    filterset_fields = ["hand"]


class ScriptManagementViewSet(ManagementViewSet):
    pagination_class = None
    queryset = Script.objects.all()
    serializer_class = ScriptManagementSerializer
