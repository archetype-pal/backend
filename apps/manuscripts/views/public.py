"""Public (read-only) manuscripts API: parts, images and their texts."""

from django.db.models import Count, Prefetch, Q, QuerySet
from django.http import HttpResponse
from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.annotations.models import Graph
from apps.common.serializers import validated_data
from apps.common.viewsets import ActionSerializerMixin
from apps.manuscripts.models import ImageText, ItemImage, ItemPart
from apps.manuscripts.serializers.actions import TeiContentSerializer
from apps.manuscripts.serializers.public import (
    ImageSerializer,
    ImageTextDetailSerializer,
    ItemPartDetailSerializer,
    ItemPartListSerializer,
)
from apps.manuscripts.services.tei import data_dpt_to_tei, format_tei, parse_graph_refs, validate_tei_wellformed
from apps.manuscripts.services.tei.document import wrap_tei_document

from ._shared import kind_from_slug, msdesc_tei_response, tei_attachment


class ItemPartViewSet(ActionSerializerMixin, ReadOnlyModelViewSet):
    # What a list row reads: the format and date labels, and `display_label`,
    # which falls back to the catalogue numbers for a part with no current item.
    queryset = (
        ItemPart.objects.select_related("historical_item__date", "historical_item__format", "current_item__repository")
        .prefetch_related("historical_item__catalogue_numbers__catalogue")
        .all()
    )
    serializer_class = ItemPartListSerializer
    action_serializer_classes = {"retrieve": ItemPartDetailSerializer}

    def get_queryset(self) -> QuerySet[ItemPart]:
        queryset: QuerySet[ItemPart] = super().get_queryset()
        if self.action != "list":
            # Only the detail payload and the TEI download read these.
            queryset = queryset.prefetch_related("historical_item__date_assessments", "msdesc_areas")
        return queryset

    @action(detail=True, methods=["get"], url_path="tei")
    def tei(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Download the part's PUBLISHED msDesc description as a TEI P5 document.

        Publication gating is unconditional here — no staff branch — because
        this URL is the public read path and its body must not vary by caller:
        it stays byte-consistent with the `msdesc_areas` the detail payload
        already exposes, and an intermediary caching one response cannot leak an
        unpublished draft. Staff who need drafts use the superuser-gated
        `management/item-parts/{id}/tei/` twin. (`ImageTextViewSet.tei` branches
        on the user instead, but there the gate is on the addressed row, so a
        hidden text is a 404 rather than a differing body.)

        An area whose stored fragment is not well-formed XML is skipped rather
        than served, so the response always parses; 404 if none survive.
        """
        return msdesc_tei_response(self.get_object(), published_only=True)


class ImageViewSet(ReadOnlyModelViewSet):
    # `annotation_count` and `image_annotation_count` are read by
    # `ImageSerializer`. Mirrors the
    # management viewset's pattern so `list` doesn't fire one COUNT
    # per row. The explicit `order_by` makes results deterministic
    # under SQLite, which can rearrange rows once a GROUP BY (added by
    # `annotate`) enters the query and Meta ordering is no longer
    # applied verbatim. `id` breaks ties, so pages never overlap.
    queryset = (
        ItemImage.objects.annotate(
            annotation_count=Count("graphs", filter=Q(graphs__deleted_at__isnull=True), distinct=True),
            image_annotation_count=Count(
                "graphs",
                filter=Q(graphs__annotation_type="image", graphs__deleted_at__isnull=True),
                distinct=True,
            ),
        )
        .order_by("item_part", "locus", "id")
        .all()
    )
    serializer_class = ImageSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_part"]

    def get_queryset(self) -> QuerySet[ItemImage]:
        # The nested `texts` are a second public read path onto ImageText and
        # owe it the same visibility rule as `ImageTextViewSet` (#210).
        queryset: QuerySet[ItemImage] = super().get_queryset()
        return queryset.prefetch_related(Prefetch("texts", queryset=ImageText.objects.visible_to(self.request.user)))


class ImageTextViewSet(ReadOnlyModelViewSet):
    """Public read-only access to ImageText.

    Anonymous users only see Live and Reviewed entries; staff see all statuses.
    """

    serializer_class = ImageTextDetailSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", "type"]

    def get_queryset(self) -> QuerySet[ImageText]:
        # Existing rows share one `created` (migration 0010), so `id` breaks ties
        # and pages never overlap.
        return ImageText.objects.select_related("item_image").visible_to(self.request.user).order_by("-created", "-id")

    @action(detail=True, methods=["get"], url_path="tei")
    def tei(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Download the text as a standalone TEI P5 document.

        The stored content is TEI; it still passes through ``data_dpt_to_tei``,
        which converts any leftover ``data-dpt`` span and leaves TEI as it is.
        Visibility follows ``get_queryset`` — anonymous callers only reach
        Live/Reviewed rows; Draft/Review 404 for them.
        """
        obj = self.get_object()
        locus = obj.item_image.locus or f"image {obj.item_image_id}"
        document = wrap_tei_document(
            data_dpt_to_tei(obj.content or ""),
            title=f"{obj.get_type_display()} — {locus}",
            source_note=f"Archetype ImageText #{obj.pk}.",
        )
        return tei_attachment(document, f"imagetext-{obj.pk}.tei")

    @action(detail=False, methods=["post"], url_path="validate-tei")
    def validate_tei(self, request: Request) -> Response:
        """Validate TEI well-formedness.

        Body: ``{"content": "<TEI fragment>"}``. Returns
        ``{"valid": bool, "errors": [{"line", "col", "message"}]}``.
        """
        content = validated_data(TeiContentSerializer, request.data)["content"]
        errors = validate_tei_wellformed(content)
        return Response({"valid": not errors, "errors": errors})

    @action(detail=False, methods=["post"], url_path="format-tei")
    def format_tei(self, request: Request) -> Response:
        """Lay out a TEI fragment for reading without changing what it says.

        Body: ``{"content": "<TEI fragment>"}``. Returns ``{"content": ...}``.
        Malformed markup is rejected rather than reflowed — the caller should
        fix it against ``validate-tei`` first, and reformatting a fragment
        someone is midway through repairing would only lose their place.
        """
        content = validated_data(TeiContentSerializer, request.data)["content"]
        if errors := validate_tei_wellformed(content):
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"content": format_tei(content)})

    @action(detail=True, methods=["get"], url_path="regions")
    def regions(self, request: Request, pk: str | None = None) -> Response:
        """Resolve the image regions linked from this text's markup.

        Parses the in-text graph references (`corresp`/`data-graph-id`) and
        returns the matching TEXT-typed Graphs with their geometry. Each entry
        flags whether the reference resolves to a TEXT Graph, so callers (and
        the integrity check) can spot dangling links.

        Trashing a region deliberately leaves its `corresp` in place, so for
        staff a trashed region resolves through `all_objects` as `exists: true`
        with geometry and `trashed: true` — a recoverable link, not a broken
        one. Everyone else stays live-only: a delete must still take the
        geometry off the public surface. Editorial regions are for signed-in
        users only, so for anonymous callers they read as `exists: false`.
        """
        obj = self.get_object()
        refs = parse_graph_refs(obj.content or "")
        wanted = {gid for ref in refs for gid in ref.graph_ids}
        manager = Graph.all_objects if request.user.is_staff else Graph.objects.visible_to(request.user)
        graphs = {
            g.id: g
            for g in manager.filter(id__in=wanted).only(
                "id", "annotation_type", "annotation", "item_image", "deleted_at"
            )
        }
        out = []
        for ref in refs:
            for gid in ref.graph_ids:
                graph = graphs.get(gid)
                out.append(
                    {
                        "graph_id": gid,
                        "element": ref.element,
                        "type": ref.type,
                        "text": ref.text,
                        "exists": graph is not None,
                        "is_text": bool(graph and graph.annotation_type == "text"),
                        "same_image": bool(graph and graph.item_image_id == obj.item_image_id),
                        "trashed": bool(graph and graph.deleted_at),
                        "geometry": graph.annotation if graph else None,
                    }
                )
        return Response({"count": len(out), "regions": out})


@api_view(["GET"])
@permission_classes([])
def sole_image_text(request: Request, item_image_id: int, kind: str) -> Response:
    """Return the single ``ImageText`` of the requested *kind* for *item_image_id*.

    Public read; anonymous callers see the row only when it is Live or Reviewed.
    Returns 404 when the row does not exist (callers treat that as "empty
    editor"; no creation occurs on read).
    """
    type_value = kind_from_slug(kind)
    qs = ImageText.objects.filter(item_image_id=item_image_id, type=type_value).visible_to(request.user)
    row = qs.first()
    if row is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(ImageTextDetailSerializer(row).data)
