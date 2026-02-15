from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.api.permissions import IsAdminUser
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
    CharacterAdminSerializer,
    CharacterDetailAdminSerializer,
    CharacterUpdateStructureSerializer,
    ComponentAdminSerializer,
    FeatureAdminSerializer,
    PositionAdminSerializer,
)


class CharacterAdminViewSet(viewsets.ModelViewSet):
    queryset = Character.objects.all()
    permission_classes = [IsAdminUser]
    pagination_class = None

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


class AllographAdminViewSet(viewsets.ModelViewSet):
    queryset = Allograph.objects.select_related("character").all()
    serializer_class = AllographAdminSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["character"]


class ComponentAdminViewSet(viewsets.ModelViewSet):
    queryset = Component.objects.prefetch_related("features").all()
    serializer_class = ComponentAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None


class FeatureAdminViewSet(viewsets.ModelViewSet):
    queryset = Feature.objects.all()
    serializer_class = FeatureAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None


class PositionAdminViewSet(viewsets.ModelViewSet):
    queryset = Position.objects.all()
    serializer_class = PositionAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None


class AllographComponentSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = AllographComponent
        fields = ["id", "allograph", "component"]


class AllographComponentAdminViewSet(viewsets.ModelViewSet):
    queryset = AllographComponent.objects.select_related("allograph", "component").all()
    serializer_class = AllographComponentSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["allograph"]


class AllographComponentFeatureSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = AllographComponentFeature
        fields = ["id", "allograph_component", "feature", "set_by_default"]


class AllographComponentFeatureAdminViewSet(viewsets.ModelViewSet):
    queryset = AllographComponentFeature.objects.select_related(
        "allograph_component", "feature"
    ).all()
    serializer_class = AllographComponentFeatureSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["allograph_component"]
