"""HTTP for the review gate and for what came through it.

Two surfaces with opposite audiences, and the split is the point. The
**proposals** endpoint is superuser-only and is the only way a machine suggestion
becomes a record; the **entity, formula and relation** endpoints are public and
read-only, and by construction contain nothing that a named human did not
approve.
"""

from django.db.models import Case, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.http import HttpResponse
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSuperuser
from apps.diplomatic import network, services

from .models import CharterEntity, Formula, FormulaOccurrence, Proposal, Relation
from .serializers import (
    CHARTER_PATHS,
    AcceptSerializer,
    CharterEntitySerializer,
    FormulaSerializer,
    ProposalDetailSerializer,
    ProposalSerializer,
    RejectSerializer,
    RelationSerializer,
)


class ProposalManagementViewSet(viewsets.ReadOnlyModelViewSet):
    """The review queue. Read, then accept or reject — never edit.

    Superusers only, like the annotation queue: the backoffice that holds the
    review page admits only superusers, so a staff permission here would open
    the API to people with no page to review from.
    """

    permission_classes = [IsSuperuser]
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
        serializer = AcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        proposal = self.get_object()
        try:
            created = services.accept(proposal, reviewer=request.user, items=serializer.validated_data.get("items"))
        except services.InvalidSelection as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except services.PipelineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({"status": proposal.status, "created": len(created), "dropped": proposal.dropped_items})

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


class CharterEntityViewSet(viewsets.ReadOnlyModelViewSet):
    """Approved entities. Public because approval is what put them here."""

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["role", "image_text"]
    queryset = CharterEntity.objects.all()
    serializer_class = CharterEntitySerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(image_text__in=services.readable_texts(self.request.user))
            .select_related(*CHARTER_PATHS)
        )


class FormulaSearch(SearchFilter):
    """Search by wording, in the texts this reader may see and no others.

    Otherwise a search would answer whether a draft contains a phrase.
    """

    def filter_queryset(self, request, queryset, view):
        readable = services.readable_texts(request.user)
        for term in self.get_search_terms(request):
            wording = FormulaOccurrence.objects.filter(
                formula=OuterRef("pk"), image_text__in=readable, excerpt__icontains=term
            )
            queryset = queryset.filter(Q(label__icontains=term) | Q(published_type__icontains=term) | Exists(wording))
        return queryset


class FormulaViewSet(viewsets.ReadOnlyModelViewSet):
    """W2.2's queryable layer: formulae and the charters that use them."""

    filter_backends = [filters.DjangoFilterBackend, FormulaSearch]
    filterset_fields = ["kind", "published_type"]
    queryset = Formula.objects.all()
    serializer_class = FormulaSerializer

    def get_queryset(self):
        # A formula is listed with the occurrences this reader may see, and not
        # at all when there are none: its exemplar was worded from one of them.
        readable = services.readable_texts(self.request.user)
        return (
            super()
            .get_queryset()
            .filter(occurrences__image_text__in=readable)
            .distinct()
            .annotate(
                reading_order=Case(
                    *(When(kind=kind, then=Value(i)) for i, kind in enumerate(Formula.READING_ORDER)),
                    default=Value(len(Formula.READING_ORDER)),
                    output_field=IntegerField(),
                )
            )
            .order_by("reading_order", "label", "pk")
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
            super()
            .get_queryset()
            .filter(image_text__in=services.readable_texts(self.request.user))
            .select_related(*CHARTER_PATHS)
        )


class DiplomaticSummaryView(APIView):
    """How much approved material the reader can see: formulae, entities, relations."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(services.public_summary(request.user))


class NetworkView(APIView):
    """W2.3: the witness and scribe network, for the site's network view."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(network.to_json(services.public_network(request.user)))


class NetworkExportView(APIView):
    """W2.3: the same network as GEXF, for Gephi and the other graph tools."""

    permission_classes = [AllowAny]

    def get(self, request):
        response = HttpResponse(
            network.to_gexf(services.public_network(request.user)), content_type="application/gexf+xml; charset=utf-8"
        )
        response["Content-Disposition"] = 'attachment; filename="archetype-network.gexf"'
        return response
