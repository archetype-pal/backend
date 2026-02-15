from django_filters import rest_framework as filters
from rest_framework import viewsets

from apps.common.api.permissions import IsAdminUser
from apps.scribes.models import Hand, Scribe, Script

from .admin_serializers import HandAdminSerializer, ScribeAdminSerializer, ScriptAdminSerializer


class ScribeAdminViewSet(viewsets.ModelViewSet):
    queryset = Scribe.objects.select_related("period").prefetch_related("hand_set").all()
    serializer_class = ScribeAdminSerializer
    permission_classes = [IsAdminUser]


class HandAdminViewSet(viewsets.ModelViewSet):
    queryset = Hand.objects.select_related(
        "scribe", "item_part", "script", "date"
    ).prefetch_related("item_part_images").all()
    serializer_class = HandAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["scribe", "item_part"]


class ScriptAdminViewSet(viewsets.ModelViewSet):
    queryset = Script.objects.all()
    serializer_class = ScriptAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None
