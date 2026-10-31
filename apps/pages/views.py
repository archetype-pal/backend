from rest_framework.mixins import ListModelMixin
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet

from apps.common.viewsets import ActionSerializerMixin, FilterablePrivilegedViewSet, UnpaginatedPrivilegedViewSet

from .models import MenuHeading, Page
from .serializers import MenuHeadingSerializer, PageListSerializer, PageSerializer


class PageViewSet(ActionSerializerMixin, ReadOnlyModelViewSet):
    """Public read-only access to published pages, for the menu dropdowns/sidebars and page content."""

    lookup_field = "slug"
    queryset = Page.objects.filter(status=Page.Status.PUBLISHED).select_related("menu_heading")
    serializer_class = PageSerializer
    action_serializer_classes = {"list": PageListSerializer}
    pagination_class = None


class PageManagementViewSet(ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = Page.objects.select_related("menu_heading")
    serializer_class = PageSerializer
    action_serializer_classes = {"list": PageListSerializer}
    lookup_field = "slug"
    filterset_fields = ["status"]
    pagination_class = None


class MenuHeadingViewSet(GenericViewSet, ListModelMixin):
    """Public list of custom menu headings. A heading without published pages is
    still listed; the frontend hides it."""

    queryset = MenuHeading.objects.all()
    serializer_class = MenuHeadingSerializer
    pagination_class = None


class MenuHeadingManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = MenuHeading.objects.all()
    serializer_class = MenuHeadingSerializer
    lookup_field = "slug"
