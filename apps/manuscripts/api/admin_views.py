from django_filters import rest_framework as filters
from rest_framework import viewsets

from apps.common.api.permissions import IsAdminUser
from apps.manuscripts.models import (
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

from .admin_serializers import (
    BibliographicSourceAdminSerializer,
    CatalogueNumberAdminSerializer,
    CurrentItemAdminSerializer,
    HistoricalItemDetailAdminSerializer,
    HistoricalItemDescriptionAdminSerializer,
    HistoricalItemListAdminSerializer,
    HistoricalItemWriteAdminSerializer,
    ImageTextAdminSerializer,
    ItemFormatAdminSerializer,
    ItemImageAdminSerializer,
    ItemPartAdminSerializer,
    RepositoryAdminSerializer,
)


class HistoricalItemAdminViewSet(viewsets.ModelViewSet):
    queryset = HistoricalItem.objects.all()
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["type", "date"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return HistoricalItemDetailAdminSerializer
        if self.action in ("create", "update", "partial_update"):
            return HistoricalItemWriteAdminSerializer
        return HistoricalItemListAdminSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            qs = qs.select_related("date", "format").prefetch_related(
                "catalogue_numbers__catalogue", "itempart_set"
            )
        elif self.action == "retrieve":
            qs = qs.select_related("date", "format").prefetch_related(
                "catalogue_numbers__catalogue",
                "descriptions__source",
                "itempart_set__current_item__repository",
                "itempart_set__images__texts",
            )
        return qs


class ItemPartAdminViewSet(viewsets.ModelViewSet):
    queryset = ItemPart.objects.select_related(
        "historical_item", "current_item__repository"
    ).all()
    serializer_class = ItemPartAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["historical_item"]


class ItemImageAdminViewSet(viewsets.ModelViewSet):
    queryset = ItemImage.objects.prefetch_related("texts", "graphs").all()
    serializer_class = ItemImageAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part"]


class ImageTextAdminViewSet(viewsets.ModelViewSet):
    queryset = ImageText.objects.select_related("item_image").all()
    serializer_class = ImageTextAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image"]


class CatalogueNumberAdminViewSet(viewsets.ModelViewSet):
    queryset = CatalogueNumber.objects.select_related("catalogue").all()
    serializer_class = CatalogueNumberAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["historical_item"]


class HistoricalItemDescriptionAdminViewSet(viewsets.ModelViewSet):
    queryset = HistoricalItemDescription.objects.select_related("source").all()
    serializer_class = HistoricalItemDescriptionAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["historical_item"]


class RepositoryAdminViewSet(viewsets.ModelViewSet):
    queryset = Repository.objects.all()
    serializer_class = RepositoryAdminSerializer
    permission_classes = [IsAdminUser]


class CurrentItemAdminViewSet(viewsets.ModelViewSet):
    queryset = CurrentItem.objects.select_related("repository").all()
    serializer_class = CurrentItemAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["repository"]


class BibliographicSourceAdminViewSet(viewsets.ModelViewSet):
    queryset = BibliographicSource.objects.all()
    serializer_class = BibliographicSourceAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None


class ItemFormatAdminViewSet(viewsets.ModelViewSet):
    queryset = ItemFormat.objects.all()
    serializer_class = ItemFormatAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None
