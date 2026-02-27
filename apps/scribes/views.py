from django_filters import rest_framework as filters
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.common.permissions import IsSuperuser
from apps.common.views import (
    BasePrivilegedViewSet,
    FilterablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)
from apps.manuscripts.models import ItemImage

from .models import Hand, Scribe, Script
from .serializers import (
    HandManagementSerializer,
    HandSerializer,
    ScribeManagementSerializer,
    ScribeSerializer,
    ScriptManagementSerializer,
)


class ScribeViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = Scribe.objects.all()
    serializer_class = ScribeSerializer


class HandViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = Hand.objects.all()
    serializer_class = HandSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part", "item_part_images", "scribe"]


class HandItemImagesForManagement(APIView):
    permission_classes = [IsSuperuser]

    def get(self, request, *args, **kwargs):
        item_part_id = request.GET.get("item_part_id")
        images = ItemImage.objects.filter(item_part_id=item_part_id)
        images_data = [{"id": img.id, "text": str(img)} for img in images]
        return Response({"images": images_data})


class ScribeManagementViewSet(BasePrivilegedViewSet):
    queryset = Scribe.objects.select_related("period").prefetch_related("hand_set").all()
    serializer_class = ScribeManagementSerializer


class HandManagementViewSet(FilterablePrivilegedViewSet):
    queryset = (
        Hand.objects.select_related("scribe", "item_part", "script", "date").prefetch_related("item_part_images").all()
    )
    serializer_class = HandManagementSerializer
    filterset_fields = ["scribe", "item_part"]


class ScriptManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Script.objects.all()
    serializer_class = ScriptManagementSerializer
