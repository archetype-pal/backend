from django.conf import settings
from django_filters import rest_framework as filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from apps.common.permissions import IsSuperuser
from apps.common.views import (
    ActionSerializerMixin,
    BasePrivilegedViewSet,
    FilterablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)

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
from .services import (
    build_image_picker_payload,
    optimize_historical_item_management_queryset,
    optimize_item_part_public_queryset,
)


class ItemPartViewSet(ActionSerializerMixin, GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = ItemPart.objects.all()
    serializer_class = ItemPartListSerializer
    action_serializer_classes = {"retrieve": ItemPartDetailSerializer}

    def get_queryset(self):
        queryset = super().get_queryset()
        return optimize_item_part_public_queryset(queryset)

class ImageViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = ItemImage.objects.all()
    serializer_class = ImageSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part"]


@api_view(["GET"])
@permission_classes([IsSuperuser])
def image_picker_content(request):
    """
    Lists media folder content for the management image picker popup.
    """
    path = request.GET.get("path", "")
    payload = build_image_picker_payload(media_root=str(settings.MEDIA_ROOT), relative_path=path)
    return Response(payload)


class HistoricalItemManagementViewSet(ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = HistoricalItem.objects.all()
    filterset_fields = ["type", "date"]

    serializer_class = HistoricalItemListManagementSerializer
    action_serializer_classes = {
        "retrieve": HistoricalItemDetailManagementSerializer,
        "create": HistoricalItemWriteManagementSerializer,
        "update": HistoricalItemWriteManagementSerializer,
        "partial_update": HistoricalItemWriteManagementSerializer,
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        return optimize_historical_item_management_queryset(queryset, action=self.action)


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
