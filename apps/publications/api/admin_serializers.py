from rest_framework import serializers

from apps.publications.models import CarouselItem, Comment, Event, Publication


class PublicationAdminSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    comment_count = serializers.IntegerField(source="comments.count", read_only=True)

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
        if obj.author:
            return obj.author.get_full_name() or obj.author.username
        return None


class PublicationListAdminSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    author_name = serializers.SerializerMethodField()
    comment_count = serializers.IntegerField(source="comments.count", read_only=True)

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
        if obj.author:
            return obj.author.get_full_name() or obj.author.username
        return None


class EventAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "slug", "content", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class CommentAdminSerializer(serializers.ModelSerializer):
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


class CarouselItemAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarouselItem
        fields = ["id", "title", "url", "image", "ordering"]
