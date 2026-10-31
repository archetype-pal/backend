"""Superuser management API for the manuscript spine: items, parts, images and lookups."""

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Prefetch, QuerySet
from django.http import HttpResponse
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.permissions import IsSuperuser
from apps.common.serializers import validated_data
from apps.common.viewsets import (
    ActionSerializerMixin,
    FilterablePrivilegedViewSet,
    SortablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)
from apps.manuscripts.filters import ItemImageManagementFilterSet
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
    MsDescArea,
    Repository,
)
from apps.manuscripts.serializers.actions import ImageTextUpsertSerializer
from apps.manuscripts.serializers.management import (
    BibliographicSourceManagementSerializer,
    CatalogueNumberManagementSerializer,
    CurrentItemManagementSerializer,
    HistoricalItemDescriptionManagementSerializer,
    HistoricalItemDetailManagementSerializer,
    HistoricalItemListManagementSerializer,
    HistoricalItemWriteManagementSerializer,
    ImageTextManagementSerializer,
    ItemFormatManagementSerializer,
    ItemImageManagementSerializer,
    ItemPartManagementSerializer,
    MsDescAreaManagementSerializer,
    RepositoryManagementSerializer,
)
from apps.manuscripts.services.historical_items import optimize_historical_item_management_queryset
from apps.manuscripts.services.image_picker import build_iiif_image_picker_payload, build_image_picker_payload
from apps.manuscripts.services.image_texts import image_text_management_queryset, upsert_sole_text
from apps.manuscripts.services.images import hand_attribution_error, with_annotation_count

from ._shared import kind_from_slug, msdesc_tei_response


@api_view(["PUT"])
@permission_classes([IsSuperuser])
def upsert_sole_image_text(request: Request, item_image_id: int, kind: str) -> Response:
    """Idempotently upsert the ``ImageText`` of *kind* for *item_image_id*.

    The (item_image, type) uniqueness invariant means there is at most one row;
    this endpoint is the simple way the frontend writes either editor without
    knowing or caring about its database id.
    """
    type_value = kind_from_slug(kind)
    defaults = validated_data(ImageTextUpsertSerializer, request.data)
    row = upsert_sole_text(item_image_id=item_image_id, type_value=type_value, defaults=defaults, actor=request.user)
    return Response(ImageTextManagementSerializer(row).data)


@api_view(["GET"])
@permission_classes([IsSuperuser])
def image_picker_content(request: Request) -> Response:
    """
    Lists media folder content for the management image picker popup.
    Falls back to filesystem scan if IIIF database browse returns nothing.
    """
    path: str = request.GET.get("path", "")
    payload = build_iiif_image_picker_payload(relative_path=path)
    if not payload["folders"] and not payload["images"]:
        payload = build_image_picker_payload(
            media_root=str(settings.MEDIA_ROOT),
            relative_path=path,
        )
    return Response(payload)


class HistoricalItemManagementViewSet(ActionSerializerMixin, SortablePrivilegedViewSet):
    queryset = HistoricalItem.objects.all()
    filterset_fields = ["type", "date"]
    search_fields = [
        "itempart__current_item__shelfmark",
        "itempart__current_item__repository__label",
        "itempart__current_item__repository__name",
        "catalogue_numbers__number",
    ]
    ordering_fields = [
        "first_repository_label",
        "first_shelfmark",
        "type",
        "date__min_weight",
        "date__max_weight",
        "image_count",
    ]

    serializer_class = HistoricalItemListManagementSerializer
    action_serializer_classes = {
        "retrieve": HistoricalItemDetailManagementSerializer,
        "create": HistoricalItemWriteManagementSerializer,
        "update": HistoricalItemWriteManagementSerializer,
        "partial_update": HistoricalItemWriteManagementSerializer,
    }

    def get_queryset(self) -> QuerySet[HistoricalItem]:
        queryset: QuerySet[HistoricalItem] = super().get_queryset()
        return optimize_historical_item_management_queryset(queryset, action=self.action)

    def filter_queryset(self, queryset: QuerySet[HistoricalItem]) -> QuerySet[HistoricalItem]:
        queryset = super().filter_queryset(queryset)
        if self.request.query_params.get("search"):
            queryset = queryset.distinct()
        return queryset


class ItemPartManagementViewSet(SortablePrivilegedViewSet):
    # No `msdesc_areas` prefetch on purpose: `ItemPartManagementSerializer`
    # doesn't nest them (the workspace gets them from the HistoricalItem detail
    # payload, `ItemPartWorkspaceSerializer`, which is prefetched there), and
    # the `tei` action below is a detail route, where a prefetch costs exactly
    # the same one extra query as touching `part.msdesc_areas` lazily. Adding it
    # here would only make every *list* page fetch TEI fragments it never
    # serializes.
    queryset = ItemPart.objects.select_related("historical_item", "current_item__repository").annotate(
        image_count=Count("images", distinct=True)
    )
    serializer_class = ItemPartManagementSerializer
    filterset_fields = ["historical_item"]

    @action(detail=True, methods=["get"], url_path="tei")
    def tei(self, request: Request, pk=None) -> HttpResponse:
        """Download EVERY msDesc area of the part, published or not.

        The editorial twin of the public `item-parts/{id}/tei/`: it exists so a
        cataloguer can round-trip a work-in-progress description through Oxygen
        or Roma before publishing it. Unpublished areas ride along only because
        `FilterablePrivilegedViewSet` restricts the whole viewset to superusers.

        Unlike the public twin this refuses to paper over a malformed fragment:
        422 with `{"errors": {area: [{line, col, message}]}}`, so the cataloguer
        gets the same diagnostics the editor's validate call returns instead of
        a quietly incomplete document.
        """
        return msdesc_tei_response(self.get_object(), published_only=False)


class ItemImageManagementViewSet(SortablePrivilegedViewSet):
    queryset = with_annotation_count(ItemImage.objects.all()).prefetch_related(
        Prefetch("texts", queryset=image_text_management_queryset(ImageText.objects.all())), "tags"
    )
    serializer_class = ItemImageManagementSerializer
    filterset_class = ItemImageManagementFilterSet

    # `tags` is a to-many, and DRF writes those after `save()`. Without a
    # transaction here `on_commit` fires immediately and queues the sync while
    # the tag rows are still unwritten. Same fix the graph serializer applies
    # around its components; move it into `AuditActorMixin` if a second
    # management serializer ever feeds a document from a to-many.
    def perform_create(self, serializer):
        with transaction.atomic():
            super().perform_create(serializer)

    def perform_update(self, serializer):
        with transaction.atomic():
            image = serializer.instance
            part = serializer.validated_data.get("item_part")
            if part is not None and part.pk != image.item_part_id:
                # Validation ran before this transaction. Lock the image and check
                # again: a graph insert takes a key-share lock on its image, so an
                # annotation saved meanwhile either commits first or waits.
                ItemImage.objects.select_for_update().get(pk=image.pk)
                if error := hand_attribution_error(image):
                    raise ValidationError({"item_part": [error]})
            super().perform_update(serializer)


class CatalogueNumberManagementViewSet(FilterablePrivilegedViewSet):
    queryset = CatalogueNumber.objects.select_related("catalogue")
    serializer_class = CatalogueNumberManagementSerializer
    filterset_fields = ["historical_item"]


class HistoricalItemDescriptionManagementViewSet(FilterablePrivilegedViewSet):
    queryset = HistoricalItemDescription.objects.select_related("source")
    serializer_class = HistoricalItemDescriptionManagementSerializer
    filterset_fields = ["historical_item"]


class MsDescAreaManagementViewSet(FilterablePrivilegedViewSet):
    """CRUD for per-part msDesc area fragments.

    No write-time schema validation (matches ImageText); well-formedness is a
    separate gated call (`image-texts/validate-tei/`). Index propagation on save/delete is a
    post_save/post_delete invariant wired in `apps.search.signals`, not a view
    concern.
    """

    queryset = MsDescArea.objects.all()
    serializer_class = MsDescAreaManagementSerializer
    filterset_fields = ["item_part", "area"]


class RepositoryManagementViewSet(SortablePrivilegedViewSet):
    queryset = Repository.objects.annotate(current_item_count=Count("currentitem"))
    serializer_class = RepositoryManagementSerializer


class CurrentItemManagementViewSet(SortablePrivilegedViewSet):
    queryset = CurrentItem.objects.select_related("repository").annotate(part_count=Count("itempart", distinct=True))
    serializer_class = CurrentItemManagementSerializer
    filterset_fields = ["repository"]
    search_fields = ["shelfmark", "repository__label", "repository__name"]
    ordering_fields = ["repository__name", "repository__label", "shelfmark", "part_count"]


class BibliographicSourceManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = BibliographicSource.objects.all()
    serializer_class = BibliographicSourceManagementSerializer


class ItemFormatManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = ItemFormat.objects.all()
    serializer_class = ItemFormatManagementSerializer
