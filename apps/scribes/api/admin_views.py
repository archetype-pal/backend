from apps.common.api.base_admin_views import (
    BaseAdminViewSet,
    FilterableAdminViewSet,
    UnpaginatedAdminViewSet,
)
from apps.scribes.models import Hand, Scribe, Script

from .admin_serializers import HandAdminSerializer, ScribeAdminSerializer, ScriptAdminSerializer


class ScribeAdminViewSet(BaseAdminViewSet):
    queryset = Scribe.objects.select_related("period").prefetch_related("hand_set").all()
    serializer_class = ScribeAdminSerializer


class HandAdminViewSet(FilterableAdminViewSet):
    queryset = Hand.objects.select_related(
        "scribe", "item_part", "script", "date"
    ).prefetch_related("item_part_images").all()
    serializer_class = HandAdminSerializer
    filterset_fields = ["scribe", "item_part"]


class ScriptAdminViewSet(UnpaginatedAdminViewSet):
    queryset = Script.objects.all()
    serializer_class = ScriptAdminSerializer
