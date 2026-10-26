from functools import reduce
import operator

from django.db.models import Q
from django.utils.html import escape
from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.viewsets import GenericViewSet

from apps.common.audit import audit_actor
from apps.common.views import (
    ActionSerializerMixin,
    BasePrivilegedViewSet,
    FilterablePrivilegedViewSet,
    SortablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)
from apps.publications.models import Comment

from .models import CarouselItem, Event, Partner, Publication
from .serializers import (
    CarouselItemManagementSerializer,
    CarouselItemSerializer,
    CommentManagementSerializer,
    CreatedCommentSerializer,
    EventDetailSerializer,
    EventListSerializer,
    EventManagementSerializer,
    PartnerManagementSerializer,
    PartnerSerializer,
    PublicationDetailSerializer,
    PublicationListManagementSerializer,
    PublicationListSerializer,
    PublicationManagementSerializer,
    PublicCommentCreateSerializer,
    SignedInCommentCreateSerializer,
)
from .services import (
    create_public_comment,
    create_signed_in_comment,
    delete_comment,
    get_public_publications_queryset,
    get_publication_management_queryset,
)


class CommentThrottle(SimpleRateThrottle):
    scope = "comment"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class EscapedTextSearchFilter(SearchFilter):
    """SearchFilter that also matches each term HTML-escaped. Guest comments are stored
    escaped (create_public_comment), so a raw search for O'Brien or & would miss them."""

    def filter_queryset(self, request, queryset, view):
        search_fields = self.get_search_fields(view, request)
        terms = self.get_search_terms(request)
        if not search_fields or not terms:
            return queryset
        lookups = [self.construct_search(str(field), queryset) for field in search_fields]
        for term in terms:
            variants = {term, escape(term)}
            queryset = queryset.filter(
                reduce(operator.or_, (Q(**{lookup: value}) for lookup in lookups for value in variants))
            )
        return queryset


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

    @action(detail=True, methods=["post"], permission_classes=[AllowAny], throttle_classes=[CommentThrottle])
    def comments(self, request, slug=None):
        publication = self.get_object()
        if not publication.allow_comments:
            raise PermissionDenied("Comments are closed on this publication.")
        signed_in = request.user.is_authenticated
        serializer_class = SignedInCommentCreateSerializer if signed_in else PublicCommentCreateSerializer
        serializer = serializer_class(data=request.data, context={"publication": publication})
        serializer.is_valid(raise_exception=True)
        if signed_in:
            comment = create_signed_in_comment(publication=publication, user=request.user, **serializer.validated_data)
        else:
            comment = create_public_comment(publication=publication, **serializer.validated_data)
        return Response(CreatedCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class CarouselItemViewSet(GenericViewSet, ListModelMixin):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemSerializer
    pagination_class = None


class PartnerViewSet(GenericViewSet, ListModelMixin):
    queryset = Partner.objects.all()
    serializer_class = PartnerSerializer
    pagination_class = None


class PublicationManagementViewSet(ActionSerializerMixin, SortablePrivilegedViewSet):
    queryset = get_publication_management_queryset()
    filterset_fields = ["status", "is_blog_post", "is_news", "is_featured"]
    search_fields = ["title", "slug"]
    ordering_fields = ["title", "comment_count", "created_at"]
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
    queryset = Comment.objects.select_related("post", "parent").filter(is_deleted=False)
    serializer_class = CommentManagementSerializer
    filter_backends = [filters.DjangoFilterBackend, EscapedTextSearchFilter]
    filterset_fields = ["post", "is_approved"]
    search_fields = ["author_name", "author_email", "content", "post__title"]

    def perform_destroy(self, instance):
        with audit_actor(getattr(self.request, "user", None)):
            delete_comment(instance)

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


class PartnerManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Partner.objects.all()
    serializer_class = PartnerManagementSerializer
    parser_classes = [MultiPartParser, JSONParser]
