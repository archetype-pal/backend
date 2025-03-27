from django_filters import rest_framework as filters
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from .models import CarouselItem, Event, Publication
from .serializers import (
    CarouselItemSerializer,
    EventDetailSerializer,
    EventListSerializer,
    PublicationDetailSerializer,
    PublicationListSerializer,
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
