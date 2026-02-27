from django_filters import rest_framework as filters
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.common.views import (
    BasePrivilegedViewSet,
    FilterablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)
from apps.publications.models import Comment

from .models import CarouselItem, Event, Publication
from .serializers import (
    CarouselItemManagementSerializer,
    CarouselItemSerializer,
    CommentManagementSerializer,
    EventDetailSerializer,
    EventListSerializer,
    EventManagementSerializer,
    PublicationDetailSerializer,
    PublicationListManagementSerializer,
    PublicationListSerializer,
    PublicationManagementSerializer,
)


class EventViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    lookup_field = "slug"
    queryset = Event.objects.all()
    serializer_class = EventDetailSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return EventListSerializer
        return EventDetailSerializer


class PublicationViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin):
    lookup_field = "slug"
    queryset = Publication.objects.all()
    serializer_class = PublicationDetailSerializer

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["is_blog_post", "is_news", "is_featured"]

    def get_serializer_class(self):
        if self.action == "list":
            return PublicationListSerializer
        return PublicationDetailSerializer

    def get_queryset(self):
        queryset = Publication.objects.filter(status=Publication.Status.PUBLISHED)

        # Check if the `recent_posts` filter is provided
        recent_posts = self.request.query_params.get("recent_posts")
        if recent_posts and recent_posts.lower() == "true":
            # Return the 5 most recent posts ordered by `published_at`
            return queryset.order_by("-published_at")[:5]
        return queryset


class CarouselItemViewSet(GenericViewSet, ListModelMixin):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemSerializer
    pagination_class = None


class PublicationManagementViewSet(FilterablePrivilegedViewSet):
    queryset = Publication.objects.select_related("author").prefetch_related("comments").all()
    filterset_fields = ["status", "is_blog_post", "is_news", "is_featured"]
    lookup_field = "slug"

    def get_serializer_class(self):
        if self.action == "list":
            return PublicationListManagementSerializer
        return PublicationManagementSerializer

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class EventManagementViewSet(BasePrivilegedViewSet):
    queryset = Event.objects.all()
    serializer_class = EventManagementSerializer
    lookup_field = "slug"


class CommentManagementViewSet(FilterablePrivilegedViewSet):
    queryset = Comment.objects.select_related("post").all()
    serializer_class = CommentManagementSerializer
    filterset_fields = ["post", "is_approved"]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        comment = self.get_object()
        comment.is_approved = True
        comment.save(update_fields=["is_approved"])
        return Response(CommentManagementSerializer(comment).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        comment = self.get_object()
        comment.is_approved = False
        comment.save(update_fields=["is_approved"])
        return Response(CommentManagementSerializer(comment).data)


class CarouselItemManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemManagementSerializer
    parser_classes = [MultiPartParser, JSONParser]
