from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.mixins import ListModelMixin
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet

from apps.common.audit import audit_actor
from apps.common.query_params import query_flag
from apps.common.serializers import validated_data
from apps.common.viewsets import (
    ActionSerializerMixin,
    BasePrivilegedViewSet,
    FilterablePrivilegedViewSet,
    SortablePrivilegedViewSet,
    UnpaginatedPrivilegedViewSet,
)

from .filters import EscapedTextSearchFilter
from .models import CarouselItem, Comment, Event, Partner, Publication
from .serializers import (
    CarouselItemManagementSerializer,
    CarouselItemSerializer,
    CommentEmailSettingSerializer,
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
    comment_emails_enabled,
    create_public_comment,
    create_signed_in_comment,
    delete_comment,
    get_public_publications_queryset,
    get_publication_management_queryset,
    set_comment_emails,
)


class CommentThrottle(SimpleRateThrottle):
    """Guests are counted by IP; a signed-in user by account, so people sharing one
    address (a campus NAT) do not share one allowance. Superusers moderate, and
    replying to a thread is part of that, so they are not throttled."""

    scope = "comment"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        user = request.user
        if user.is_authenticated:
            if user.is_superuser:
                return None
            ident = f"user-{user.pk}"
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class EventViewSet(ActionSerializerMixin, ReadOnlyModelViewSet):
    lookup_field = "slug"
    queryset = Event.objects.all()
    serializer_class = EventDetailSerializer
    action_serializer_classes = {"list": EventListSerializer}


class PublicationViewSet(ActionSerializerMixin, ReadOnlyModelViewSet):
    lookup_field = "slug"
    queryset = Publication.objects.all()
    serializer_class = PublicationDetailSerializer

    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["is_blog_post", "is_news", "is_featured"]
    action_serializer_classes = {"list": PublicationListSerializer}

    def get_queryset(self):
        return get_public_publications_queryset(
            recent_posts=query_flag(self.request.query_params, "recent_posts"),
            action=self.action,
        )

    @action(detail=True, methods=["post"], permission_classes=[AllowAny], throttle_classes=[CommentThrottle])
    def comments(self, request, slug=None):
        publication = self.get_object()
        if not publication.allow_comments:
            raise PermissionDenied("Comments are closed on this publication.")
        signed_in = request.user.is_authenticated
        serializer_class = SignedInCommentCreateSerializer if signed_in else PublicCommentCreateSerializer
        data = validated_data(serializer_class, request.data, publication=publication)
        if signed_in:
            comment = create_signed_in_comment(publication=publication, user=request.user, **data)
        else:
            comment = create_public_comment(publication=publication, **data)
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

    def _set_approved(self, approved: bool) -> Response:
        comment = self.get_object()
        comment.is_approved = approved
        comment.save(update_fields=["is_approved"])
        return Response(self.get_serializer(comment).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._set_approved(True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._set_approved(False)

    @action(detail=False, methods=["get"], url_path="email-setting")
    def email_setting(self, request):
        return Response(CommentEmailSettingSerializer({"email_enabled": comment_emails_enabled(request.user)}).data)

    @email_setting.mapping.patch
    def update_email_setting(self, request):
        enabled = validated_data(CommentEmailSettingSerializer, request.data)["email_enabled"]
        set_comment_emails(request.user, enabled)
        return Response(CommentEmailSettingSerializer({"email_enabled": enabled}).data)


class CarouselItemManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = CarouselItem.objects.all()
    serializer_class = CarouselItemManagementSerializer
    parser_classes = [MultiPartParser, JSONParser]


class PartnerManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Partner.objects.all()
    serializer_class = PartnerManagementSerializer
    parser_classes = [MultiPartParser, JSONParser]
