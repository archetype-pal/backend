from django_filters import rest_framework as filters
from rest_framework import viewsets

from apps.common.permissions import IsSuperuser

from .models import MLJob
from .serializers import MLJobListSerializer, MLJobSerializer


class MLJobFilterSet(filters.FilterSet):
    """Filters for the ledger, including the reverse target lookup.

    `target_type` + `target_id` answer the question the ledger exists for —
    *which model produced this record* — from the record's side.
    """

    target_type = filters.CharFilter(field_name="targets__target_type")
    target_id = filters.NumberFilter(field_name="targets__target_id")

    class Meta:
        model = MLJob
        fields = ["task", "provider", "status", "model_name", "target_type", "target_id"]


class MLJobManagementViewSet(viewsets.ReadOnlyModelViewSet):
    """Superuser-gated read access to the inference ledger.

    Read-only rather than a `ModelViewSet`: the ledger is append-only and
    machine-written, so an HTTP write path would be a way to forge provenance.
    That is also why it does not use `BasePrivilegedViewSet`, which is a
    `ModelViewSet` and carries the audit-actor mixin for human edits.
    """

    permission_classes = [IsSuperuser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = MLJobFilterSet
    queryset = MLJob.objects.select_related("actor").prefetch_related("targets")
    serializer_class = MLJobSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return MLJobListSerializer
        return MLJobSerializer
