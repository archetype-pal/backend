from rest_framework import serializers

from apps.publications.models import CarouselItem, Comment, Event, Publication
from apps.users.serializers import UserSummarySerializer


def _author_display_name(user) -> str | None:
    if not user:
        return None
    return user.get_full_name() or user.username


class CarouselItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarouselItem
        fields = ["title", "url", "image"]


class EventListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "slug", "created_at"]


class EventDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "content", "slug", "created_at"]


class PublicationListSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer()

    number_of_comments = serializers.IntegerField(source="approved_comments_count", read_only=True)

    class Meta:
        model = Publication
        fields = ["id", "title", "slug", "preview", "author", "number_of_comments", "published_at", "created_at"]


class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ["author_name", "content", "created_at"]


class PublicationDetailSerializer(PublicationListSerializer):
    author = UserSummarySerializer()
    comments = serializers.SerializerMethodField()

    def get_comments(self, obj):
        approved_comments = getattr(obj, "approved_comments_prefetched", None)
        if approved_comments is None:
            approved_comments = Comment.objects.filter(post=obj, is_approved=True)
        return CommentSerializer(approved_comments, many=True).data

    class Meta:
        model = Publication
        fields = PublicationListSerializer.Meta.fields + ["content", "comments"]


class PublicationManagementSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    comment_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Publication
        fields = [
            "id",
            "title",
            "slug",
            "content",
            "preview",
            "author",
            "author_name",
            "status",
            "keywords",
            "is_blog_post",
            "is_news",
            "is_featured",
            "allow_comments",
            "similar_posts",
            "published_at",
            "created_at",
            "updated_at",
            "comment_count",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_author_name(self, obj):
        return _author_display_name(obj.author)


class PublicationListManagementSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    comment_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Publication
        fields = [
            "id",
            "title",
            "slug",
            "status",
            "is_blog_post",
            "is_news",
            "is_featured",
            "author",
            "author_name",
            "published_at",
            "created_at",
            "comment_count",
        ]

    def get_author_name(self, obj):
        return _author_display_name(obj.author)


class EventManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "slug", "content", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class CommentManagementSerializer(serializers.ModelSerializer):
    post_title = serializers.CharField(source="post.title", read_only=True)

    class Meta:
        model = Comment
        fields = [
            "id",
            "post",
            "post_title",
            "content",
            "author_name",
            "author_email",
            "author_website",
            "is_approved",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class CarouselItemManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarouselItem
        fields = ["id", "title", "url", "image", "ordering"]
