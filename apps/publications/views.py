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
        return Publication.objects.filter(status=Publication.Status.PUBLISHED)


class CarouselItemViewSet(GenericViewSet, ListModelMixin):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemSerializer
    pagination_class = None
