from django_filters import rest_framework as filters
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.common.api.permissions import IsAdminUser
from apps.manuscripts.models import ItemImage

from .models import Hand, Scribe
from .serializers import HandSerializer, ScribeSerializer


class ScribeViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = Scribe.objects.all()
    serializer_class = ScribeSerializer


class HandViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = Hand.objects.all()
    serializer_class = HandSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part", "item_part_images", "scribe"]


class HandItemImagesForAdmin(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        item_part_id = request.GET.get("item_part_id")
        images = ItemImage.objects.filter(item_part_id=item_part_id)
        images_data = [{"id": img.id, "text": str(img)} for img in images]
        return Response({"images": images_data})
