from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from apps.common.views import (
    BasePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)

from .models import Allograph, AllographComponent, AllographComponentFeature, Character, Component, Feature, Position
from .serializers import (
    AllographComponentFeatureManagementSerializer,
    AllographComponentManagementSerializer,
    AllographManagementSerializer,
    AllographSerializer,
    CharacterDetailManagementSerializer,
    CharacterManagementSerializer,
    CharacterUpdateStructureSerializer,
    ComponentManagementSerializer,
    FeatureManagementSerializer,
    PositionManagementSerializer,
    PositionSerializer,
)


class AllographListView(ListAPIView):
    queryset = Allograph.objects.all()
    serializer_class = AllographSerializer
    pagination_class = None


class PositionListView(ListAPIView):
    queryset = Position.objects.all()
    serializer_class = PositionSerializer
    pagination_class = None


class CharacterManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Character.objects.all()

    def get_serializer_class(self):
        if self.action in ("retrieve", "update_structure"):
            return CharacterDetailManagementSerializer
        return CharacterManagementSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.prefetch_related("allograph_set")
        return queryset

    @action(detail=True, methods=["post"], url_path="update-structure")
    def update_structure(self, request, pk=None):
        character = self.get_object()
        serializer = CharacterUpdateStructureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        character = serializer.update_structure(character, serializer.validated_data)
        return Response(CharacterDetailManagementSerializer(character).data)


class AllographManagementViewSet(BasePrivilegedViewSet):
    queryset = Allograph.objects.select_related("character").all()
    serializer_class = AllographManagementSerializer
    filterset_fields = ["character"]


class ComponentManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Component.objects.prefetch_related("features").all()
    serializer_class = ComponentManagementSerializer


class FeatureManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Feature.objects.all()
    serializer_class = FeatureManagementSerializer


class PositionManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Position.objects.all()
    serializer_class = PositionManagementSerializer


class AllographComponentManagementViewSet(BasePrivilegedViewSet):
    queryset = AllographComponent.objects.select_related("allograph", "component").all()
    serializer_class = AllographComponentManagementSerializer
    filterset_fields = ["allograph"]


class AllographComponentFeatureManagementViewSet(BasePrivilegedViewSet):
    queryset = AllographComponentFeature.objects.select_related("allograph_component", "feature").all()
    serializer_class = AllographComponentFeatureManagementSerializer
    filterset_fields = ["allograph_component"]
