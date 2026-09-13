"""HTTP for the review gate and for what came through it.

Two surfaces with opposite audiences, and the split is the point. The
**proposals** endpoint is staff-only and is the only way a machine suggestion
becomes a record; the **entity, formula and relation** endpoints are public and
read-only, and by construction contain nothing that a named human did not
approve.
"""

from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.diplomatic import services

from .models import CharterEntity, Formula, Proposal, Relation
from .serializers import (
    CharterEntitySerializer,
    FormulaSerializer,
    ProposalListSerializer,
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
        if self.action == "list":
            return ProposalListSerializer
        return ProposalSerializer

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


class CharterEntityViewSet(viewsets.ReadOnlyModelViewSet):
    """Approved entities. Public because approval is what put them here."""

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["role", "image_text"]
    queryset = CharterEntity.objects.all()
    serializer_class = CharterEntitySerializer


class FormulaViewSet(viewsets.ReadOnlyModelViewSet):
    """W2.2's queryable layer: formulae and the charters that use them."""

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["kind", "published_type"]
    queryset = Formula.objects.prefetch_related("occurrences")
    serializer_class = FormulaSerializer


class RelationViewSet(viewsets.ReadOnlyModelViewSet):
    """W3.3's approved triples."""

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["predicate", "image_text"]
    queryset = Relation.objects.all()
    serializer_class = RelationSerializer
