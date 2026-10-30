"""Superuser management of image texts: CRUD, the editorial workflow, region links, HTR import, export."""

from django.db.models import QuerySet
from django.http import HttpResponse, JsonResponse
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.common.exports import to_csv
from apps.common.permissions import IsSuperuser
from apps.common.serializers import validated_data
from apps.common.viewsets import FilterablePrivilegedViewSet
from apps.manuscripts.filters import ImageTextManagementFilterSet
from apps.manuscripts.models import ImageText
from apps.manuscripts.serializers.actions import (
    BulkActionSerializer,
    ImportHtrSerializer,
    LinkRegionSerializer,
    TransitionSerializer,
    UnlinkElementSerializer,
    UnlinkRegionSerializer,
)
from apps.manuscripts.serializers.management import ImageTextManagementSerializer, StatusTransitionSerializer
from apps.manuscripts.services import image_texts
from apps.manuscripts.services.image_texts import image_text_management_queryset
from apps.manuscripts.services.text_monitoring import text_monitoring_overview


class ImageTextManagementViewSet(FilterablePrivilegedViewSet):
    # Existing rows share one `created` (migration 0010), so `id` breaks ties
    # and pages never overlap.
    queryset = ImageText.objects.select_related("item_image", "item_image__item_part", "review_assignee").order_by(
        "-created", "-id"
    )
    serializer_class = ImageTextManagementSerializer
    filterset_class = ImageTextManagementFilterSet
    search_fields = ["content", "language"]

    def get_queryset(self) -> QuerySet[ImageText]:
        queryset: QuerySet[ImageText] = super().get_queryset()
        # Only the read actions serialize a list or a fresh row. The export
        # action uses .values_list().iterator(), which rejects a prefetch, and
        # the write actions only need the row itself.
        if self.action in ("list", "retrieve"):
            queryset = image_text_management_queryset(queryset)
        return queryset

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request: Request, pk=None) -> Response:
        """Explicit status transition with audit trail.

        Body: ``{"to_status": "Review", "note": "...", "assignee": <user_id?>}``.
        """
        text = self.get_object()
        data = validated_data(TransitionSerializer, request.data)
        assignee = data.get("assignee")
        image_texts.transition_texts(
            [text],
            to_status=data["to_status"],
            note=data["note"],
            assignee_id=assignee.pk if assignee else None,
            actor=request.user,
        )
        return Response(self.get_serializer(text).data)

    @action(detail=True, methods=["post"], url_path="link-region")
    def link_region(self, request: Request, pk=None) -> Response:
        """Link a text element to an image region.

        ``{"element_index": <int>, "geometry": <GeoJSON Feature>}`` creates a
        TEXT graph; ``{"element_index": <int>, "graph_id": <int>}`` links an
        existing region of this image (a trashed one is restored). Returns the
        graph id and the updated content; 201 only when a graph was created.
        """
        text = self.get_object()
        data = validated_data(LinkRegionSerializer, request.data)
        graph, created = image_texts.link_region(
            text,
            element_index=data["element_index"],
            geometry=data.get("geometry"),
            graph_id=data.get("graph_id"),
            actor=request.user,
        )
        return Response(
            {"graph_id": graph.id, "content": text.content},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="unlink-region")
    def unlink_region(self, request: Request, pk=None) -> Response:
        """Delete a region graph and strip its reference from every text of the image."""
        text = self.get_object()
        data = validated_data(UnlinkRegionSerializer, request.data)
        image_texts.unlink_region(text, graph_id=data["graph_id"], actor=request.user)
        return Response({"content": text.content})

    @action(detail=True, methods=["post"], url_path="unlink-element")
    def unlink_element(self, request: Request, pk=None) -> Response:
        """Remove one element↔region link, leaving the graph and its other links intact."""
        text = self.get_object()
        data = validated_data(UnlinkElementSerializer, request.data)
        image_texts.unlink_element(
            text, element_index=data["element_index"], graph_id=data["graph_id"], actor=request.user
        )
        return Response({"content": text.content})

    @action(detail=False, methods=["post"], url_path="import-htr")
    def import_htr(self, request: Request) -> Response:
        """Create a Draft text from PAGE-XML / ALTO HTR output; returns ``{"id", "lines", "regions"}``."""
        data = validated_data(ImportHtrSerializer, request.data)
        result = image_texts.import_htr(
            item_image_id=data["item_image"],
            fmt=data["format"],
            xml=data["xml"],
            kind=data["type"],
            language=data["language"],
            actor=request.user,
        )
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request: Request) -> Response:
        """Backoffice monitoring dashboard over every image-text (status matrix, coverage, activity)."""
        return Response(text_monitoring_overview())

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request: Request, pk=None) -> Response:
        """Full audit log for a single image-text (the list payload only carries `last_transition`)."""
        rows = self.get_object().status_transitions.select_related("actor").all()
        return Response(StatusTransitionSerializer(rows, many=True).data)

    @action(detail=False, methods=["post"], url_path="bulk_action")
    def bulk_action(self, request: Request) -> Response:
        """Apply `transition`, `set_language` or `delete` to many rows at once.

        Body: ``{"ids": [int, ...], "action": "<name>", "payload": {...}}``;
        returns ``{"affected": N}``. All-or-nothing.
        """
        data = validated_data(BulkActionSerializer, request.data)
        if not data["ids"]:
            return Response({"affected": 0})
        rows = ImageText.objects.filter(pk__in=data["ids"])
        payload = data["payload"]
        if data["action"] == "transition":
            affected = image_texts.transition_texts(
                rows.select_for_update(),
                to_status=payload["to_status"],
                note=payload.get("note", ""),
                actor=request.user,
            )
        elif data["action"] == "set_language":
            # `language=""` is valid: it clears a wrong tag back to "(unset)".
            affected = image_texts.set_language(
                rows.select_for_update(), language=str(payload["language"]), actor=request.user
            )
        else:
            affected = image_texts.delete_texts(rows, actor=request.user)
        return Response({"affected": affected})

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request: Request) -> HttpResponse:
        """Every row matching the list filters as CSV (default) or JSON (``?export_format=json``)."""
        raw_format = request.query_params.get("export_format") or request.query_params.get("format")
        fmt = (raw_format or "csv").strip().lower()
        if fmt not in ("csv", "json"):
            return Response({"detail": "Unsupported export format."}, status=status.HTTP_400_BAD_REQUEST)
        rows = image_texts.export_rows(self.filter_queryset(self.get_queryset()))
        if fmt == "json":
            response = JsonResponse(rows, safe=False, json_dumps_params={"indent": 2})
        else:
            response = HttpResponse(to_csv(rows, image_texts.EXPORT_COLUMNS), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="image-texts.{fmt}"'
        return response


class ReviewQueueViewSet(GenericViewSet, ListModelMixin):
    """Read-only feed of texts in `Review`, oldest first, each with its latest transition."""

    serializer_class = ImageTextManagementSerializer
    permission_classes = [IsSuperuser]
    pagination_class = None

    def get_queryset(self):
        pending = ImageText.objects.filter(status=ImageText.Status.REVIEW)
        return image_text_management_queryset(pending).order_by("modified")
