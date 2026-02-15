from apps.common.api.base_admin_views import (
    BaseAdminViewSet,
    FilterableAdminViewSet,
    UnpaginatedAdminViewSet,
)
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


class HistoricalItemAdminViewSet(FilterableAdminViewSet):
    queryset = HistoricalItem.objects.all()
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
            qs = qs.select_related("date", "format").prefetch_related("catalogue_numbers__catalogue", "itempart_set")
        elif self.action == "retrieve":
            qs = qs.select_related("date", "format").prefetch_related(
                "catalogue_numbers__catalogue",
                "descriptions__source",
                "itempart_set__current_item__repository",
                "itempart_set__images__texts",
            )
        return qs


class ItemPartAdminViewSet(FilterableAdminViewSet):
    queryset = ItemPart.objects.select_related("historical_item", "current_item__repository").all()
    serializer_class = ItemPartAdminSerializer
    filterset_fields = ["historical_item"]


class ItemImageAdminViewSet(FilterableAdminViewSet):
    queryset = ItemImage.objects.prefetch_related("texts", "graphs").all()
    serializer_class = ItemImageAdminSerializer
    filterset_fields = ["item_part"]


class ImageTextAdminViewSet(FilterableAdminViewSet):
    queryset = ImageText.objects.select_related("item_image").all()
    serializer_class = ImageTextAdminSerializer
    filterset_fields = ["item_image"]


class CatalogueNumberAdminViewSet(FilterableAdminViewSet):
    queryset = CatalogueNumber.objects.select_related("catalogue").all()
    serializer_class = CatalogueNumberAdminSerializer
    filterset_fields = ["historical_item"]


class HistoricalItemDescriptionAdminViewSet(FilterableAdminViewSet):
    queryset = HistoricalItemDescription.objects.select_related("source").all()
    serializer_class = HistoricalItemDescriptionAdminSerializer
    filterset_fields = ["historical_item"]


class RepositoryAdminViewSet(BaseAdminViewSet):
    queryset = Repository.objects.all()
    serializer_class = RepositoryAdminSerializer


class CurrentItemAdminViewSet(FilterableAdminViewSet):
    queryset = CurrentItem.objects.select_related("repository").all()
    serializer_class = CurrentItemAdminSerializer
    filterset_fields = ["repository"]


class BibliographicSourceAdminViewSet(UnpaginatedAdminViewSet):
    queryset = BibliographicSource.objects.all()
    serializer_class = BibliographicSourceAdminSerializer


class ItemFormatAdminViewSet(UnpaginatedAdminViewSet):
    queryset = ItemFormat.objects.all()
    serializer_class = ItemFormatAdminSerializer
