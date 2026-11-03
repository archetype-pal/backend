from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from apps.common.query_params import query_flag
from apps.common.serializers import validated_data
from apps.common.viewsets import (
    ActionSerializerMixin,
    ManagementViewSet,
)

from .models import Allograph, Character, Component, Feature, Position
from .serializers import (
    AllographSerializer,
    AllographSummarySerializer,
    CharacterDetailManagementSerializer,
    CharacterManagementSerializer,
    CharacterUpdateStructureSerializer,
    ComponentManagementSerializer,
    FeatureManagementSerializer,
    PositionSerializer,
)
from .services import CharacterStructureService


class AllographListView(ListAPIView):
    serializer_class = AllographSerializer
    pagination_class = None

    def _is_light(self) -> bool:
        return query_flag(self.request.query_params, "light")

    def get_serializer_class(self):
        return AllographSummarySerializer if self._is_light() else AllographSerializer

    def get_queryset(self):
        base = Allograph.objects.select_related("character")
        if self._is_light():
            # Labels only — skip the nested component/feature/position prefetch.
            return base.all()
        return base.prefetch_related(
            "positions",
            "allographcomponent_set__component__features",
            "allographcomponent_set__allographcomponentfeature_set__feature",
        )


class CharacterManagementViewSet(ActionSerializerMixin, ManagementViewSet):
    pagination_class = None
    queryset = Character.objects.all()
    serializer_class = CharacterManagementSerializer
    action_serializer_classes = {
        "retrieve": CharacterDetailManagementSerializer,
        "update_structure": CharacterDetailManagementSerializer,
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.prefetch_related("allograph_set")
        return queryset

    @action(detail=True, methods=["post"], url_path="update-structure")
    def update_structure(self, request, pk=None):
        data = validated_data(CharacterUpdateStructureSerializer, request.data)
        character = CharacterStructureService().update_structure(character=self.get_object(), validated_data=data)
        return Response(CharacterDetailManagementSerializer(character).data)


class ComponentManagementViewSet(ManagementViewSet):
    pagination_class = None
    queryset = Component.objects.prefetch_related("features")
    serializer_class = ComponentManagementSerializer


class FeatureManagementViewSet(ManagementViewSet):
    pagination_class = None
    queryset = Feature.objects.all()
    serializer_class = FeatureManagementSerializer


class PositionManagementViewSet(ManagementViewSet):
    pagination_class = None
    queryset = Position.objects.all()
    serializer_class = PositionSerializer
