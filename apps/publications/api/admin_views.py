from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.common.api.base_admin_views import (
    BaseAdminViewSet,
    FilterableAdminViewSet,
    UnpaginatedAdminViewSet,
)
from apps.publications.models import CarouselItem, Comment, Event, Publication

from .admin_serializers import (
    CarouselItemAdminSerializer,
    CommentAdminSerializer,
    EventAdminSerializer,
    PublicationAdminSerializer,
    PublicationListAdminSerializer,
)


class PublicationAdminViewSet(FilterableAdminViewSet):
    queryset = Publication.objects.select_related("author").prefetch_related("comments").all()
    filterset_fields = ["status", "is_blog_post", "is_news", "is_featured"]
    lookup_field = "slug"

    def get_serializer_class(self):
        if self.action == "list":
            return PublicationListAdminSerializer
        return PublicationAdminSerializer

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class EventAdminViewSet(BaseAdminViewSet):
    queryset = Event.objects.all()
    serializer_class = EventAdminSerializer
    lookup_field = "slug"


class CommentAdminViewSet(FilterableAdminViewSet):
    queryset = Comment.objects.select_related("post").all()
    serializer_class = CommentAdminSerializer
    filterset_fields = ["post", "is_approved"]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        comment = self.get_object()
        comment.is_approved = True
        comment.save(update_fields=["is_approved"])
        return Response(CommentAdminSerializer(comment).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        comment = self.get_object()
        comment.is_approved = False
        comment.save(update_fields=["is_approved"])
        return Response(CommentAdminSerializer(comment).data)


class CarouselItemAdminViewSet(UnpaginatedAdminViewSet):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemAdminSerializer
    parser_classes = [MultiPartParser, JSONParser]
