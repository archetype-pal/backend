"""HTTP for the review gate and for what came through it.

Two surfaces with opposite audiences, and the split is the point. The
**proposals** endpoint is staff-only and is the only way a machine suggestion
becomes a record; the **entity, formula and relation** endpoints are public and
read-only, and by construction contain nothing that a named human did not
approve.
"""

from django.db import models
from django.db.models import Prefetch
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.diplomatic import services
from apps.manuscripts.models import ImageText

from .models import CharterEntity, Formula, FormulaOccurrence, Proposal, Relation
from .serializers import (
    CHARTER_PATHS,
    CharterEntitySerializer,
    FormulaSerializer,
    ProposalDetailSerializer,
    ProposalSerializer,
    RejectSerializer,
    RelationSerializer,
)


class ProposalManagementViewSet(viewsets.ReadOnlyModelViewSet):
    """The review queue. Read, then accept or reject — never edit.

    `IsAdminUser` (is_staff) rather than `IsSuperuser`: reviewing proposals is
    the domain expert's job, and §8.6 already makes reviewer capacity the
    programme's real rate limit. Requiring a superuser to clear the queue would
    narrow that bottleneck further for no gain in safety — acceptance is
    recorded against the named reviewer either way.
    """

    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["pipeline", "status", "source_type", "source_id"]
    queryset = Proposal.objects.select_related("reviewer", "ml_job")
    serializer_class = ProposalSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProposalDetailSerializer
        return ProposalSerializer

    def list(self, request, *args, **kwargs):
        # The page's source charters are fetched together: `source_id` is not a
        # foreign key, so the serializer could only follow it row by row.
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)
        context = {**self.get_serializer_context(), "sources": services.proposal_sources(rows)}
        serializer = self.get_serializer(rows, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def depth(self, request):
        """Pending proposals, in total and per pipeline: the reviewer-capacity number."""
        by_pipeline = services.pending_by_pipeline()
        return Response({"pending": sum(by_pipeline.values()), "by_pipeline": by_pipeline})

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        proposal = self.get_object()
        try:
            created = services.accept(proposal, reviewer=request.user)
        except services.PipelineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({"status": proposal.status, "created": len(created)})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        serializer = RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        proposal = self.get_object()
        try:
            services.reject(proposal, reviewer=request.user, reason=serializer.validated_data.get("reason", ""))
        except services.PipelineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({"status": proposal.status})


def _readable_texts(request) -> models.QuerySet:
    """The texts this reader may see, by the same rule as the texts themselves.

    The pipelines read drafts as well as published texts, so an approved record
    can come from a text the public cannot open. Its names, and a formula's
    excerpt above all, are that draft's words. Visibility is decided here, when
    the record is read, because a text's status can change after approval.
    """
    return ImageText.objects.visible_to(request.user).values("pk")


class CharterEntityViewSet(viewsets.ReadOnlyModelViewSet):
    """Approved entities. Public because approval is what put them here."""

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["role", "image_text"]
    queryset = CharterEntity.objects.all()
    serializer_class = CharterEntitySerializer

    def get_queryset(self):
        return (
            super().get_queryset().filter(image_text__in=_readable_texts(self.request)).select_related(*CHARTER_PATHS)
        )


class FormulaViewSet(viewsets.ReadOnlyModelViewSet):
    """W2.2's queryable layer: formulae and the charters that use them."""

    filter_backends = [filters.DjangoFilterBackend, SearchFilter]
    filterset_fields = ["kind", "published_type"]
    search_fields = ["label", "exemplar", "published_type"]
    queryset = Formula.objects.all()
    serializer_class = FormulaSerializer

    def get_queryset(self):
        # A formula is listed with the occurrences this reader may see, and not
        # at all when there are none: its exemplar was worded from one of them.
        readable = _readable_texts(self.request)
        return (
            super()
            .get_queryset()
            .filter(occurrences__image_text__in=readable)
            .distinct()
            .prefetch_related(
                Prefetch(
                    "occurrences",
                    queryset=FormulaOccurrence.objects.filter(image_text__in=readable).select_related(*CHARTER_PATHS),
                )
            )
        )


class RelationViewSet(viewsets.ReadOnlyModelViewSet):
    """W3.3's approved triples."""

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["predicate", "image_text"]
    queryset = Relation.objects.all()
    serializer_class = RelationSerializer

    def get_queryset(self):
        return (
            super().get_queryset().filter(image_text__in=_readable_texts(self.request)).select_related(*CHARTER_PATHS)
        )
