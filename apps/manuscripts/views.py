import csv
import io
from xml.etree.ElementTree import ParseError

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.http import HttpResponse
from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.annotations.models import Graph
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
from .services.htr import alto_to_lines, lines_to_tei, page_xml_to_lines
from .services.tei import (
    add_graph_ref,
    data_dpt_to_tei,
    parse_graph_refs,
    remove_graph_ref,
    validate_tei_wellformed,
)
from .services.tei.document import wrap_tei_document


class ItemPartViewSet(ActionSerializerMixin, GenericViewSet, ListModelMixin, RetrieveModelMixin):
    queryset = (
        ItemPart.objects.select_related("historical_item__date", "current_item__repository")
        .prefetch_related("historical_item__date_assessments")
        .all()
    )
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

    @action(detail=True, methods=["get"], url_path="tei")
    def tei(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Download the text as a standalone TEI P5 document.

        Converts the stored ``data-dpt`` content to TEI on read (Phase H.12).
        Visibility follows ``get_queryset`` — anonymous callers only reach
        Live/Reviewed rows; Draft/Review 404 for them.
        """
        obj = self.get_object()
        locus = obj.item_image.locus or f"image {obj.item_image_id}"
        body = data_dpt_to_tei(obj.content or "")
        document = wrap_tei_document(
            body,
            title=f"{obj.get_type_display()} — {locus}",
            source_note=f"Archetype ImageText #{obj.pk}.",
        )
        response = HttpResponse(document, content_type="application/tei+xml; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="imagetext-{obj.pk}.tei"'
        return response

    @action(detail=False, methods=["post"], url_path="validate-tei")
    def validate_tei(self, request: Request) -> Response:
        """Validate TEI well-formedness (Phase H.10).

        Body: ``{"content": "<TEI fragment>"}``. Returns
        ``{"valid": bool, "errors": [{"line", "col", "message"}]}``.
        """
        content = request.data.get("content", "")
        if not isinstance(content, str):
            return Response(
                {"valid": False, "errors": [{"line": 1, "col": 0, "message": "content must be a string"}]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        errors = validate_tei_wellformed(content)
        return Response({"valid": not errors, "errors": errors})

    @action(detail=True, methods=["get"], url_path="regions")
    def regions(self, request: Request, pk: str | None = None) -> Response:
        """Resolve the image regions linked from this text's markup.

        Parses the in-text graph references (`corresp`/`data-graph-id`) and
        returns the matching TEXT-typed Graphs with their geometry. Each entry
        flags whether the reference resolves to a live TEXT Graph, so callers
        (and the integrity check) can spot dangling links. (text_annotation
        plan, Phase 1.)
        """
        obj = self.get_object()
        refs = parse_graph_refs(obj.content or "")
        wanted = {gid for ref in refs for gid in ref.graph_ids}
        graphs = {
            g.id: g
            for g in Graph.objects.filter(id__in=wanted).only("id", "annotation_type", "annotation", "item_image")
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
                        "geometry": graph.annotation if graph else None,
                    }
                )
        return Response({"count": len(out), "regions": out})


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

    def filter_queryset(self, queryset: QuerySet[ItemImage]) -> QuerySet[ItemImage]:
        queryset = super().filter_queryset(queryset)
        params = self.request.query_params
        # The dashboard's coverage donut surfaces three buckets the regular
        # filterset can't express: "no text at all", "no transcription",
        # "no translation". Without these the donut segments can't drill
        # down to actionable rows.
        has_text = params.get("has_text")
        if has_text in {"true", "1"}:
            queryset = queryset.filter(Exists(ImageText.objects.filter(item_image_id=OuterRef("pk"))))
        elif has_text in {"false", "0"}:
            queryset = queryset.filter(~Exists(ImageText.objects.filter(item_image_id=OuterRef("pk"))))
        has_transcription = params.get("has_transcription")
        if has_transcription in {"true", "1"}:
            queryset = queryset.filter(
                Exists(ImageText.objects.filter(item_image_id=OuterRef("pk"), type=ImageText.Type.TRANSCRIPTION))
            )
        elif has_transcription in {"false", "0"}:
            queryset = queryset.filter(
                ~Exists(ImageText.objects.filter(item_image_id=OuterRef("pk"), type=ImageText.Type.TRANSCRIPTION))
            )
        has_translation = params.get("has_translation")
        if has_translation in {"true", "1"}:
            queryset = queryset.filter(
                Exists(ImageText.objects.filter(item_image_id=OuterRef("pk"), type=ImageText.Type.TRANSLATION))
            )
        elif has_translation in {"false", "0"}:
            queryset = queryset.filter(
                ~Exists(ImageText.objects.filter(item_image_id=OuterRef("pk"), type=ImageText.Type.TRANSLATION))
            )
        return queryset


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

    @action(detail=True, methods=["post"], url_path="link-region")
    def link_region(self, request: Request, pk=None) -> Response:
        """Track A — link a region to a text element.

        Two modes:
        - NEW region: ``{"element_index": <int>, "geometry": <GeoJSON Feature>}``
          creates a TEXT-typed Graph and embeds a `corresp="#gid-N"` ref onto the
          element_index-th linkable element of this text.
        - EXISTING region: ``{"element_index": <int>, "graph_id": <int>}`` adds a
          ref for an existing region graph to another element (e.g. the same
          region's translation phrase) — no new graph. The graph must be a TEXT
          graph of this image.

        Returns the graph id and the updated content.
        """
        text = self.get_object()
        element_index = request.data.get("element_index")
        if not isinstance(element_index, int) or element_index < 0:
            return Response(
                {"detail": "element_index (non-negative int) is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        graph_id = request.data.get("graph_id")
        geometry = request.data.get("geometry")
        if graph_id is not None and not isinstance(graph_id, int):
            return Response({"detail": "graph_id must be an int."}, status=status.HTTP_400_BAD_REQUEST)
        if graph_id is None and not isinstance(geometry, dict):
            return Response(
                {"detail": "geometry (GeoJSON) or graph_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        graph = None
        if graph_id is not None:
            graph = Graph.objects.filter(id=graph_id, annotation_type="text", item_image_id=text.item_image_id).first()
            if graph is None:
                return Response(
                    {"detail": "No text region with that graph_id on this image."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            with transaction.atomic():
                if graph is None:
                    graph = Graph.objects.create(
                        item_image_id=text.item_image_id,
                        annotation=geometry,
                        annotation_type="text",
                    )
                text.content = add_graph_ref(text.content or "", element_index, graph.id)
                text.save(update_fields=["content", "modified"])
        except IndexError:
            return Response(
                {"detail": f"No linkable element at index {element_index}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"graph_id": graph.id, "content": text.content},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="unlink-region")
    def unlink_region(self, request: Request, pk=None) -> Response:
        """Track A — remove a text↔region link.

        Body: ``{"graph_id": <int>}``. Deletes the region's TEXT Graph and
        strips its `corresp`/`data-graph-id` reference from every text of the
        same image (so no dangling ref is left). Idempotent on the content side;
        returns the updated content of the addressed text.
        """
        text = self.get_object()
        graph_id = request.data.get("graph_id")
        if not isinstance(graph_id, int):
            return Response({"detail": "graph_id (int) is required."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            for sibling in ImageText.objects.filter(item_image_id=text.item_image_id):
                updated = remove_graph_ref(sibling.content or "", graph_id)
                if updated != (sibling.content or ""):
                    sibling.content = updated
                    sibling.save(update_fields=["content", "modified"])
            Graph.objects.filter(id=graph_id, annotation_type="text", item_image_id=text.item_image_id).delete()

        text.refresh_from_db()
        return Response({"content": text.content}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="import-htr")
    def import_htr(self, request: Request) -> Response:
        """Track C3 — create a Draft ImageText from PAGE-XML / ALTO HTR output.

        Body: ``{"item_image": <id>, "format": "page"|"alto", "type": "...",
        "language": "...", "xml": "<…>"}``. Parses the HTR into lines, emits TEI
        (one ``<seg type="line">`` per line, ``<lb/>``-separated), materialises a
        TEXT Graph per line that has a polygon, and embeds the matching
        ``corresp`` references. Returns the new image-text id.
        """
        item_image_id = request.data.get("item_image")
        fmt = request.data.get("format")
        xml = request.data.get("xml")
        if not item_image_id or fmt not in ("page", "alto") or not isinstance(xml, str):
            return Response(
                {"detail": "item_image, format ('page'|'alto') and xml are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        kind = request.data.get("type", ImageText.Type.TRANSCRIPTION)
        if kind not in ImageText.Type.values:
            return Response({"detail": "Unknown type."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lines = page_xml_to_lines(xml) if fmt == "page" else alto_to_lines(xml)
        except ParseError:
            return Response({"detail": "Malformed XML."}, status=status.HTTP_400_BAD_REQUEST)
        if not lines:
            return Response({"detail": "No text lines found in the document."}, status=status.HTTP_400_BAD_REQUEST)

        if not ItemImage.objects.filter(pk=item_image_id).exists():
            return Response({"detail": "Unknown item_image."}, status=status.HTTP_404_NOT_FOUND)
        # One ImageText per (item_image, type) — surface a clean conflict instead
        # of letting the unique constraint raise a 500 inside the atomic block.
        if ImageText.objects.filter(item_image_id=item_image_id, type=kind).exists():
            return Response(
                {"detail": f"A {kind} already exists for this image."},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            graph_ids: list[int | None] = []
            for line in lines:
                geom = line.geojson()
                if geom is None:
                    graph_ids.append(None)
                    continue
                graph = Graph.objects.create(item_image_id=item_image_id, annotation=geom, annotation_type="text")
                graph_ids.append(graph.id)
            content = lines_to_tei(lines, graph_ids=graph_ids)
            image_text = ImageText.objects.create(
                item_image_id=item_image_id,
                content=content,
                type=kind,
                status=ImageText.Status.DRAFT,
                language=request.data.get("language", ""),
            )
        return Response(
            {"id": image_text.id, "lines": len(lines), "regions": sum(1 for g in graph_ids if g)},
            status=status.HTTP_201_CREATED,
        )

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

    @action(detail=False, methods=["post"], url_path="bulk_action")
    def bulk_action(self, request: Request) -> Response:
        """Apply one of a small allow-list of edits to many rows in one shot.

        Body: ``{"ids": [int,...], "action": "<name>", "payload": {...}}``

        Actions:
        * ``transition``  — payload ``{"to_status": "...", "note": "..."?}``;
          one `StatusTransition` row per text is written so the audit log
          stays honest.
        * ``set_language`` — payload ``{"language": "..."}``; intended for
          the dashboard's "(unset)" cleanup workflow.
        * ``delete`` — no payload; hard-deletes the rows.

        Returns ``{"affected": N}``. All-or-nothing inside a single
        transaction so a partial failure doesn't leave half the selection
        in an unexpected state.
        """
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response({"detail": "`ids` must be a list of integers."}, status=status.HTTP_400_BAD_REQUEST)
        if not ids:
            return Response({"affected": 0})
        action_name = request.data.get("action")
        payload = request.data.get("payload") or {}

        qs = ImageText.objects.filter(pk__in=ids)
        actor = request.user if request.user.is_authenticated else None

        if action_name == "transition":
            to_status = payload.get("to_status")
            if to_status not in ImageText.Status.values:
                return Response({"detail": "Unknown status."}, status=status.HTTP_400_BAD_REQUEST)
            note = payload.get("note", "")
            with transaction.atomic():
                texts = list(qs.select_for_update())
                transitions = []
                for text in texts:
                    from_status = text.status
                    text.status = to_status
                    if to_status != ImageText.Status.REVIEW:
                        text.review_assignee = None
                    text.save(update_fields=["status", "review_assignee", "modified"])
                    transitions.append(
                        StatusTransition(
                            image_text=text,
                            actor=actor,
                            from_status=from_status,
                            to_status=to_status,
                            note=note,
                        )
                    )
                StatusTransition.objects.bulk_create(transitions)
            return Response({"affected": len(texts)})

        if action_name == "set_language":
            if "language" not in payload:
                return Response({"detail": "`language` is required."}, status=status.HTTP_400_BAD_REQUEST)
            # `language=""` is a valid target — it's how an editor clears a
            # wrong tag back to the "(unset)" bucket.
            language = str(payload["language"])
            affected = qs.update(language=language)
            return Response({"affected": affected})

        if action_name == "delete":
            affected, _ = qs.delete()
            return Response({"affected": affected})

        return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request: Request) -> HttpResponse:
        """Stream all rows matching the current filters as CSV or JSON.

        The in-browser DataTable export only sees the current page, which
        is useless for "give me every Draft transcription with no language"
        — that's hundreds of rows across many pages. Honours the same
        filter set as ``list``.

        Format selection via ``?format=csv|json`` (default csv).
        """
        queryset = self.filter_queryset(self.get_queryset())
        fmt = request.query_params.get("format", "csv").lower()
        # Drop the full HTML `content` — exports are for triage and the
        # column would dwarf everything else. The char-count + status is
        # what editors filter on.
        rows = list(
            queryset.values(
                "id",
                "item_image_id",
                "item_image__item_part_id",
                "item_image__locus",
                "type",
                "status",
                "language",
                "review_assignee__username",
                "created",
                "modified",
            )
        )
        # Char counts come from the model, not the values() projection, so
        # we don't pull every HTML blob across the wire.
        char_counts = dict(queryset.values_list("id", "content").iterator())

        if fmt == "json":
            payload = [
                {
                    "id": r["id"],
                    "item_image_id": r["item_image_id"],
                    "item_part_id": r["item_image__item_part_id"],
                    "locus": r["item_image__locus"] or "",
                    "type": r["type"],
                    "status": r["status"],
                    "language": r["language"],
                    "review_assignee_username": r["review_assignee__username"],
                    "char_count": len(char_counts.get(r["id"]) or ""),
                    "is_empty": not (char_counts.get(r["id"]) or ""),
                    "created": r["created"].isoformat(),
                    "modified": r["modified"].isoformat(),
                }
                for r in rows
            ]
            response = HttpResponse(content_type="application/json")
            response["Content-Disposition"] = 'attachment; filename="image-texts.json"'
            import json

            response.write(json.dumps(payload, indent=2))
            return response

        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(
            [
                "id",
                "item_image_id",
                "item_part_id",
                "locus",
                "type",
                "status",
                "language",
                "review_assignee",
                "char_count",
                "is_empty",
                "created",
                "modified",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r["id"],
                    r["item_image_id"],
                    r["item_image__item_part_id"] or "",
                    _csv_safe(r["item_image__locus"] or ""),
                    r["type"],
                    r["status"],
                    _csv_safe(r["language"]),
                    _csv_safe(r["review_assignee__username"] or ""),
                    len(char_counts.get(r["id"]) or ""),
                    "true" if not char_counts.get(r["id"]) else "false",
                    r["created"].isoformat(),
                    r["modified"].isoformat(),
                ]
            )
        response = HttpResponse(buf.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="image-texts.csv"'
        return response


_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Neutralise CSV-injection prefixes the way escape_csv_field does in JS.

    Excel/Sheets treat a cell starting with ``=``/``+``/``-``/``@`` as a
    formula; a researcher-edited language string of ``=cmd|'/c calc'!A1``
    would otherwise execute when an admin opens the export. Prepending a
    single quote turns the cell into literal text without affecting how
    most tooling reads it back.
    """
    if value and value[0] in _CSV_DANGEROUS_PREFIXES:
        return "'" + value
    return value


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
