from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.api.base_admin_views import (
    BaseAdminViewSet,
    UnpaginatedAdminViewSet,
)
from apps.symbols_structure.models import (
    Allograph,
    AllographComponent,
    AllographComponentFeature,
    Character,
    Component,
    Feature,
    Position,
)

from .admin_serializers import (
    AllographAdminSerializer,
    AllographComponentAdminSerializer,
    AllographComponentFeatureAdminSerializer,
    CharacterAdminSerializer,
    CharacterDetailAdminSerializer,
    CharacterUpdateStructureSerializer,
    ComponentAdminSerializer,
    FeatureAdminSerializer,
    PositionAdminSerializer,
)


class CharacterAdminViewSet(UnpaginatedAdminViewSet):
    queryset = Character.objects.all()

    def get_serializer_class(self):
        if self.action in ("retrieve", "update_structure"):
            return CharacterDetailAdminSerializer
        return CharacterAdminSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            qs = qs.prefetch_related("allograph_set")
        return qs

    @action(detail=True, methods=["post"], url_path="update-structure")
    def update_structure(self, request, pk=None):
        """
        Accepts the full nested tree for a character and reconciles
        creates/updates/deletes in a single transaction.
        """
        character = self.get_object()
        serializer = CharacterUpdateStructureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        character = serializer.update_structure(character, serializer.validated_data)
        return Response(CharacterDetailAdminSerializer(character).data)


class AllographAdminViewSet(BaseAdminViewSet):
    queryset = Allograph.objects.select_related("character").all()
    serializer_class = AllographAdminSerializer
    filterset_fields = ["character"]


class ComponentAdminViewSet(UnpaginatedAdminViewSet):
    queryset = Component.objects.prefetch_related("features").all()
    serializer_class = ComponentAdminSerializer


class FeatureAdminViewSet(UnpaginatedAdminViewSet):
    queryset = Feature.objects.all()
    serializer_class = FeatureAdminSerializer


class PositionAdminViewSet(UnpaginatedAdminViewSet):
    queryset = Position.objects.all()
    serializer_class = PositionAdminSerializer


class AllographComponentAdminViewSet(BaseAdminViewSet):
    queryset = AllographComponent.objects.select_related("allograph", "component").all()
    serializer_class = AllographComponentAdminSerializer
    filterset_fields = ["allograph"]


class AllographComponentFeatureAdminViewSet(BaseAdminViewSet):
    queryset = AllographComponentFeature.objects.select_related("allograph_component", "feature").all()
    serializer_class = AllographComponentFeatureAdminSerializer
    filterset_fields = ["allograph_component"]
