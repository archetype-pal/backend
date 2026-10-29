from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsOwnerOrReadOnly
from apps.common.viewsets import ActionSerializerMixin

from .serializers import WorksetDetailSerializer, WorksetListSerializer
from .services import get_citable_worksets_queryset, get_owned_worksets_queryset


class WorksetViewSet(ActionSerializerMixin, ModelViewSet):
    """User-owned lightbox worksets.

    - list / create: the authenticated owner's own worksets.
    - retrieve: any Public workset (anonymously citable) or the owner's own.
    - update / destroy: owner only.
    """

    lookup_field = "public_id"
    serializer_class = WorksetDetailSerializer
    action_serializer_classes = {"list": WorksetListSerializer}

    def get_permissions(self):
        if self.action == "retrieve":
            return [AllowAny()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsOwnerOrReadOnly()]
        return [IsAuthenticated()]

    def get_queryset(self):
        # retrieve is the only action visible beyond the owner, so only it widens
        # the queryset to Public-or-owned; everything else stays owner-scoped.
        if self.action == "retrieve":
            return get_citable_worksets_queryset(self.request.user)
        return get_owned_worksets_queryset(self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
