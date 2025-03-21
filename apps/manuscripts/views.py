import os

from django_filters import rest_framework as filters
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet
from django.http import JsonResponse
from django.conf import settings

from .models import ItemImage, ItemPart
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


class ImageViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = ItemImage.objects.all()
    serializer_class = ImageSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part"]


def image_picker_content(request):
    """
    This view is used to list the content of a folder within the django media
    directory. It is used by the image picker popup in the admin interface.
    """
    path = request.GET.get("path", "")
    media_dir = os.path.join(settings.MEDIA_ROOT, path)

    folders = []
    images = []

    if os.path.exists(media_dir):
        for item in os.listdir(media_dir):
            item_path = os.path.join(media_dir, item)
            if os.path.isdir(item_path):
                folders.append(
                    {
                        "name": item,
                        "path": os.path.join(path, item),
                    }
                )
            elif item.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                images.append(
                    {
                        "name": item,
                        "path": os.path.join(path, item),
                        "url": f"{settings.MEDIA_URL}/{os.path.join(path, item)}",
                    }
                )

    return JsonResponse(
        {
            "folders": folders,
            "images": images,
        }
    )
