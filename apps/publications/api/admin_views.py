from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.api.permissions import IsAdminUser
from apps.publications.models import CarouselItem, Comment, Event, Publication

from .admin_serializers import (
    CarouselItemAdminSerializer,
    CommentAdminSerializer,
    EventAdminSerializer,
    PublicationAdminSerializer,
    PublicationListAdminSerializer,
)


class PublicationAdminViewSet(viewsets.ModelViewSet):
    queryset = Publication.objects.select_related("author").prefetch_related("comments").all()
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["status", "is_blog_post", "is_news", "is_featured"]
    lookup_field = "slug"

    def get_serializer_class(self):
        if self.action == "list":
            return PublicationListAdminSerializer
        return PublicationAdminSerializer

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class EventAdminViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventAdminSerializer
    permission_classes = [IsAdminUser]
    lookup_field = "slug"


class CommentAdminViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.select_related("post").all()
    serializer_class = CommentAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
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


class CarouselItemAdminViewSet(viewsets.ModelViewSet):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None
