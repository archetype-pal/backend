import os

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django_filters import rest_framework as filters
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from apps.common.views import (
    BasePrivilegedViewSet,
    FilterablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)

from .iiif import get_iiif_url
from .models import (
    BibliographicSource,
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    HistoricalItemDescription,
    ImageText,
    ItemFormat,
    ItemImage,
    ItemPart,
    Repository,
)
from .serializers import (
    BibliographicSourceManagementSerializer,
    CatalogueNumberManagementSerializer,
    CurrentItemManagementSerializer,
    HistoricalItemDescriptionManagementSerializer,
    HistoricalItemDetailManagementSerializer,
    HistoricalItemListManagementSerializer,
    HistoricalItemWriteManagementSerializer,
    ImageSerializer,
    ImageTextManagementSerializer,
    ItemFormatManagementSerializer,
    ItemImageManagementSerializer,
    ItemPartDetailSerializer,
    ItemPartListSerializer,
    ItemPartManagementSerializer,
    RepositoryManagementSerializer,
)


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


@user_passes_test(lambda user: user.is_authenticated and user.is_superuser)
def image_picker_content(request):
    """
    Lists media folder content for the management image picker popup.
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
            elif item.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".tif")):
                images.append(
                    {"name": item, "path": os.path.join(path, item), "url": get_iiif_url(os.path.join(path, item))}
                )

    return JsonResponse(
        {
            "folders": folders,
            "images": images,
        }
    )


class HistoricalItemManagementViewSet(FilterablePrivilegedViewSet):
    queryset = HistoricalItem.objects.all()
    filterset_fields = ["type", "date"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return HistoricalItemDetailManagementSerializer
        if self.action in ("create", "update", "partial_update"):
            return HistoricalItemWriteManagementSerializer
        return HistoricalItemListManagementSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.select_related("date", "format").prefetch_related(
                "catalogue_numbers__catalogue",
                "itempart_set__current_item__repository",
                "itempart_set__images",
            )
        elif self.action == "retrieve":
            queryset = queryset.select_related("date", "format").prefetch_related(
                "catalogue_numbers__catalogue",
                "descriptions__source",
                "itempart_set__current_item__repository",
                "itempart_set__images__texts",
            )
        return queryset


class ItemPartManagementViewSet(FilterablePrivilegedViewSet):
    queryset = ItemPart.objects.select_related("historical_item", "current_item__repository").all()
    serializer_class = ItemPartManagementSerializer
    filterset_fields = ["historical_item"]


class ItemImageManagementViewSet(FilterablePrivilegedViewSet):
    queryset = ItemImage.objects.prefetch_related("texts", "graphs").all()
    serializer_class = ItemImageManagementSerializer
    filterset_fields = ["item_part"]


class ImageTextManagementViewSet(FilterablePrivilegedViewSet):
    queryset = ImageText.objects.select_related("item_image").all()
    serializer_class = ImageTextManagementSerializer
    filterset_fields = ["item_image"]


class CatalogueNumberManagementViewSet(FilterablePrivilegedViewSet):
    queryset = CatalogueNumber.objects.select_related("catalogue").all()
    serializer_class = CatalogueNumberManagementSerializer
    filterset_fields = ["historical_item"]


class HistoricalItemDescriptionManagementViewSet(FilterablePrivilegedViewSet):
    queryset = HistoricalItemDescription.objects.select_related("source").all()
    serializer_class = HistoricalItemDescriptionManagementSerializer
    filterset_fields = ["historical_item"]


class RepositoryManagementViewSet(BasePrivilegedViewSet):
    queryset = Repository.objects.all()
    serializer_class = RepositoryManagementSerializer


class CurrentItemManagementViewSet(FilterablePrivilegedViewSet):
    queryset = CurrentItem.objects.select_related("repository").all()
    serializer_class = CurrentItemManagementSerializer
    filterset_fields = ["repository"]


class BibliographicSourceManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = BibliographicSource.objects.all()
    serializer_class = BibliographicSourceManagementSerializer


class ItemFormatManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = ItemFormat.objects.all()
    serializer_class = ItemFormatManagementSerializer
