from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from apps.common.views import ActionSerializerMixin, FilterablePrivilegedViewSet

from .models import Page
from .serializers import PageListSerializer, PageSerializer


class PageViewSet(ActionSerializerMixin, GenericViewSet, ListModelMixin, RetrieveModelMixin):
    """Public read-only access to published pages, for the About menu/sidebar and page content."""

    lookup_field = "slug"
    queryset = Page.objects.filter(status=Page.Status.PUBLISHED)
    serializer_class = PageSerializer
    action_serializer_classes = {"list": PageListSerializer}
    pagination_class = None


class PageManagementViewSet(ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = Page.objects.all()
    serializer_class = PageSerializer
    action_serializer_classes = {"list": PageListSerializer}
    lookup_field = "slug"
    filterset_fields = ["status"]
    pagination_class = None
