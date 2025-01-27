from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .models import ItemPart
from .serializers import ImageSerializer, ItemPartDetailSerializer, ItemPartListSerializer


class ItemPartViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = ItemPart.objects.all()
    serializer_class = ItemPartListSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.select_related("historical_item", "current_item")
        return queryset

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ItemPartDetailSerializer
        return ItemPartListSerializer

    @action(detail=True, methods=["get"])
    def images(self, *args, **kwargs):
        item_part = self.get_object()
        queryset = item_part.images.all()

        serializer = ImageSerializer(queryset, many=True)
        return Response(serializer.data)
