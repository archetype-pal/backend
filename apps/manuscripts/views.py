from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
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
    StatusTransition,
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
    ImageTextDetailSerializer,
    ImageTextManagementSerializer,
    ItemFormatManagementSerializer,
    ItemImageManagementSerializer,
    ItemPartDetailSerializer,
    ItemPartListSerializer,
    ItemPartManagementSerializer,
    RepositoryManagementSerializer,
    StatusTransitionSerializer,
)
from .services import (
    build_iiif_image_picker_payload,
    build_image_picker_payload,
    optimize_historical_item_management_queryset,
)


class ItemPartViewSet(ActionSerializerMixin, GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = ItemPart.objects.select_related("historical_item", "current_item").all()
    serializer_class = ItemPartListSerializer
    action_serializer_classes = {"retrieve": ItemPartDetailSerializer}


class ImageViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    # `annotation_count` and `image_annotation_count` are read by
    # `ImageSerializer`. Mirrors the
    # management viewset's pattern so `list` doesn't fire one COUNT
    # per row. The explicit `order_by` makes results deterministic
    # under SQLite, which can rearrange rows once a GROUP BY (added by
    # `annotate`) enters the query and Meta ordering is no longer
    # applied verbatim.
    queryset = (
        ItemImage.objects.annotate(
            annotation_count=Count("graphs", distinct=True),
            image_annotation_count=Count(
                "graphs",
                filter=Q(graphs__annotation_type="image"),
                distinct=True,
            ),
        )
        .order_by("item_part", "locus")
        .all()
    )
    serializer_class = ImageSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part"]


class ImageTextViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    """Public read-only access to ImageText.

    Anonymous users only see Live and Reviewed entries; staff see all statuses.
    """

    serializer_class = ImageTextDetailSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", "type"]

    def get_queryset(self) -> QuerySet[ImageText]:
        queryset = ImageText.objects.select_related("item_image").all()
        user = self.request.user
        if not (user.is_authenticated and user.is_staff):
            queryset = queryset.filter(status__in=[ImageText.Status.LIVE, ImageText.Status.REVIEWED])
        return queryset


def _kind_from_slug(slug: str) -> str | None:
    """Map ``"transcription"`` / ``"translation"`` URL segments to the model enum value."""
    if slug == "transcription":
        return ImageText.Type.TRANSCRIPTION
    if slug == "translation":
        return ImageText.Type.TRANSLATION
    return None


@api_view(["GET"])
@permission_classes([])
def sole_image_text(request: Request, item_image_id: int, kind: str) -> Response:
    """Return the single ``ImageText`` of the requested *kind* for *item_image_id*.

    Public read; anonymous callers see the row only when it is Live or Reviewed.
    Returns 404 when the row does not exist (callers treat that as "empty
    editor"; no creation occurs on read).
    """
    type_value = _kind_from_slug(kind)
    if type_value is None:
        return Response({"detail": "Unknown kind."}, status=400)
    qs = ImageText.objects.filter(item_image_id=item_image_id, type=type_value)
    user = request.user
    if not (user.is_authenticated and user.is_staff):
        qs = qs.filter(status__in=[ImageText.Status.LIVE, ImageText.Status.REVIEWED])
    row = qs.first()
    if row is None:
        return Response({"detail": "Not found."}, status=404)
    return Response(ImageTextDetailSerializer(row).data)


@api_view(["PUT"])
@permission_classes([IsSuperuser])
def upsert_sole_image_text(request: Request, item_image_id: int, kind: str) -> Response:
    """Idempotently upsert the ``ImageText`` of *kind* for *item_image_id*.

    The (item_image, type) uniqueness invariant means there is at most one row;
    this endpoint is the simple way the frontend writes either editor without
    knowing or caring about its database id.
    """
    type_value = _kind_from_slug(kind)
    if type_value is None:
        return Response({"detail": "Unknown kind."}, status=400)
    if not ItemImage.objects.filter(pk=item_image_id).exists():
        return Response({"detail": "Unknown item_image."}, status=404)
    payload = request.data or {}
    defaults = {
        "content": payload.get("content", ""),
        "status": payload.get("status", ImageText.Status.DRAFT),
        "language": payload.get("language", ""),
    }
    row, _ = ImageText.objects.update_or_create(
        item_image_id=item_image_id,
        type=type_value,
        defaults=defaults,
    )
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


class HistoricalItemManagementViewSet(ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = HistoricalItem.objects.all()
    filterset_fields = ["type", "date"]
    search_fields = [
        "itempart__current_item__shelfmark",
        "itempart__current_item__repository__label",
        "itempart__current_item__repository__name",
        "catalogue_numbers__number",
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


class ItemPartManagementViewSet(FilterablePrivilegedViewSet):
    queryset = (
        ItemPart.objects.select_related("historical_item", "current_item__repository")
        .annotate(image_count=Count("images", distinct=True))
        .all()
    )
    serializer_class = ItemPartManagementSerializer
    filterset_fields = ["historical_item"]


class ItemImageManagementViewSet(FilterablePrivilegedViewSet):
    queryset = (
        ItemImage.objects.prefetch_related("texts").annotate(annotation_count=Count("graphs", distinct=True)).all()
    )
    serializer_class = ItemImageManagementSerializer
    filterset_fields = ["item_part"]


class ImageTextManagementViewSet(FilterablePrivilegedViewSet):
    queryset = ImageText.objects.select_related("item_image", "item_image__item_part", "review_assignee").all()
    serializer_class = ImageTextManagementSerializer
    filterset_fields = ["item_image", "status", "type", "review_assignee"]
    search_fields = ["content", "language"]

    def filter_queryset(self, queryset: QuerySet[ImageText]) -> QuerySet[ImageText]:
        queryset = super().filter_queryset(queryset)
        params = self.request.query_params
        # `language=__unset__` selects rows where the field is the empty string
        # — that bucket is the largest one on the dashboard (~900 rows) but
        # `?language=` URL-decodes to a blank value which DjangoFilterBackend
        # treats as "no filter", so we need an explicit sentinel.
        if params.get("language") == "__unset__":
            queryset = queryset.filter(language="")
        # `empty=true|false` toggles the empty-content bucket the dashboard
        # surfaces but the management filter set never exposed.
        empty = params.get("empty")
        if empty in {"true", "1"}:
            queryset = queryset.filter(content="")
        elif empty in {"false", "0"}:
            queryset = queryset.exclude(content="")
        return queryset

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request: Request, pk=None) -> Response:
        """Phase G — explicit status transition with audit trail.

        Body: ``{"to_status": "Review", "note": "...", "assignee": <user_id?>}``
        Records a `StatusTransition` row, optionally assigns a reviewer.
        """
        text = self.get_object()
        to_status = request.data.get("to_status")
        if to_status not in ImageText.Status.values:
            return Response({"detail": "Unknown status."}, status=status.HTTP_400_BAD_REQUEST)
        from_status = text.status
        note = request.data.get("note", "")
        assignee_id = request.data.get("assignee")

        with transaction.atomic():
            text.status = to_status
            if to_status == ImageText.Status.REVIEW and assignee_id:
                text.review_assignee_id = assignee_id
            elif to_status != ImageText.Status.REVIEW:
                # Clear the assignee once the row leaves Review.
                text.review_assignee = None
            text.save(update_fields=["status", "review_assignee", "modified"])
            StatusTransition.objects.create(
                image_text=text,
                actor=request.user if request.user.is_authenticated else None,
                from_status=from_status,
                to_status=to_status,
                note=note,
            )
        return Response(self.get_serializer(text).data)

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request: Request, pk=None) -> Response:
        """Full audit log for a single image-text.

        The base serializer only carries `last_transition` to keep the list
        payload small; the editor wants the whole timeline, so we expose it
        as a sibling action rather than inflating every list response.
        """
        text = self.get_object()
        rows = text.status_transitions.select_related("actor").all()
        return Response(StatusTransitionSerializer(rows, many=True).data)


class ReviewQueueViewSet(GenericViewSet, ListModelMixin):
    """Phase G.1 — read-only feed of `ImageText` rows in `Review` status.

    Used by `/backoffice/review-queue`. Sorted by oldest-pending-first
    so reviewers don't lose track of the long tail. Each row carries
    the latest transition (who sent it, when, with what note) so the
    UI doesn't need a second round trip.
    """

    serializer_class = ImageTextManagementSerializer
    permission_classes = [IsSuperuser]
    pagination_class = None

    def get_queryset(self):
        return (
            ImageText.objects.filter(status=ImageText.Status.REVIEW)
            .select_related("item_image", "review_assignee")
            .order_by("modified")
        )


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
    queryset = (
        CurrentItem.objects.select_related("repository").annotate(part_count=Count("itempart", distinct=True)).all()
    )
    serializer_class = CurrentItemManagementSerializer
    filterset_fields = ["repository"]
    search_fields = ["shelfmark", "repository__label", "repository__name"]


class BibliographicSourceManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = BibliographicSource.objects.all()
    serializer_class = BibliographicSourceManagementSerializer


class ItemFormatManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = ItemFormat.objects.all()
    serializer_class = ItemFormatManagementSerializer
