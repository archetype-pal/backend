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

    # Deferred and applied together in `filter_queryset`. `targets` is
    # multi-valued, so two chained `.filter()` calls join it twice and match a
    # job whose type came from one target and whose id came from another — the
    # one query this table exists for, answering with false positives.
    target_type = filters.CharFilter(method="_deferred")
    target_id = filters.NumberFilter(method="_deferred")

    class Meta:
        model = MLJob
        fields = ["task", "provider", "status", "model_name", "target_type", "target_id"]

    def _deferred(self, queryset, name, value):
        return queryset

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        target_type = self.form.cleaned_data.get("target_type")
        target_id = self.form.cleaned_data.get("target_id")
        terms = {}
        if target_type:
            terms["targets__target_type"] = target_type
        if target_id is not None:
            terms["targets__target_id"] = target_id
        if terms:
            # One join, and distinct: a job with three graph targets is one job.
            queryset = queryset.filter(**terms).distinct()
        return queryset


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
