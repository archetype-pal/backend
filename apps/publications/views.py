from django_filters import rest_framework as filters
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.common.views import (
    ActionSerializerMixin,
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
from .services import (
    get_public_publications_queryset,
    get_publication_management_queryset,
    set_comment_approval,
)


class EventViewSet(ActionSerializerMixin, GenericViewSet, ListModelMixin, RetrieveModelMixin):
    lookup_field = "slug"
    queryset = Event.objects.all()
    serializer_class = EventDetailSerializer
    action_serializer_classes = {"list": EventListSerializer}


class PublicationViewSet(ActionSerializerMixin, GenericViewSet, ListModelMixin, RetrieveModelMixin):
    lookup_field = "slug"
    queryset = Publication.objects.all()
    serializer_class = PublicationDetailSerializer

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["is_blog_post", "is_news", "is_featured"]
    action_serializer_classes = {"list": PublicationListSerializer}

    def get_queryset(self):
        recent_posts = self.request.query_params.get("recent_posts")
        return get_public_publications_queryset(
            recent_posts=bool(recent_posts and recent_posts.lower() == "true"),
            action=self.action,
        )


class CarouselItemViewSet(GenericViewSet, ListModelMixin):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemSerializer
    pagination_class = None


class PublicationManagementViewSet(ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = get_publication_management_queryset()
    filterset_fields = ["status", "is_blog_post", "is_news", "is_featured"]
    lookup_field = "slug"

    serializer_class = PublicationManagementSerializer
    action_serializer_classes = {"list": PublicationListManagementSerializer}

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
        comment = set_comment_approval(comment=comment, is_approved=True)
        return Response(CommentManagementSerializer(comment).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        comment = self.get_object()
        comment = set_comment_approval(comment=comment, is_approved=False)
        return Response(CommentManagementSerializer(comment).data)


class CarouselItemManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemManagementSerializer
    parser_classes = [MultiPartParser, JSONParser]
