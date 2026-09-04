from html import unescape
from html.parser import HTMLParser
from typing import Any

from django_tagulous.utils import parse_tags
from rest_framework import serializers

from apps.publications.models import CarouselItem, Comment, Event, Partner, Publication
from apps.users.serializers import UserSummarySerializer


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def _has_visible_html_text(value: str | None) -> bool:
    if not value:
        return False

    parser = _HTMLTextExtractor()
    parser.feed(value)
    text = unescape(" ".join(parser.parts)).replace("\xa0", " ").strip()
    return bool(text)


def _author_display_name(user: Any) -> str | None:
    if not user:
        return None
    full_name = user.get_full_name()
    if isinstance(full_name, str) and full_name:
        return full_name

    username = user.username
    return username if isinstance(username, str) and username else None


class CarouselItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarouselItem
        fields = ["title", "url", "image"]


class PartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = ["id", "name", "url", "logo", "ordering"]


class EventListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "slug", "created_at"]


class EventDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "content", "slug", "created_at"]


class TagStringField(serializers.CharField):
    """Serializes a Tagulous TagField to/from a comma-separated string.

    Counting is delegated to Tagulous' own parser rather than splitting on
    commas: the model parses with `space_delimiter=True`, so "a b" commits two
    tags. Splitting on commas here would pass a payload the save then rejects
    with a bare ValueError -- a 500 where this raises a 400.
    """

    def to_representation(self, value):
        return str(value)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        options = self._tag_options()
        tags = parse_tags(value, space_delimiter=options.space_delimiter)
        if options.max_count and len(tags) > options.max_count:
            raise serializers.ValidationError(
                f"No more than {options.max_count} keywords are allowed (got {len(tags)})."
            )
        return value

    def _tag_options(self):
        return self.parent.Meta.model._meta.get_field(self.field_name).tag_options


class PublicationListSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer()
    keywords = TagStringField(read_only=True)
    number_of_comments = serializers.IntegerField(source="approved_comments_count", read_only=True)

    class Meta:
        model = Publication
        fields = [
            "id",
            "title",
            "slug",
            "preview",
            "author",
            "keywords",
            "is_blog_post",
            "is_news",
            "is_featured",
            "number_of_comments",
            "published_at",
            "created_at",
        ]


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
    keywords = TagStringField(required=False, allow_blank=True)

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
        read_only_fields = ["author", "created_at", "updated_at"]

    def get_author_name(self, obj):
        return _author_display_name(obj.author)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        status = attrs.get("status", getattr(self.instance, "status", Publication.Status.DRAFT))
        if status != Publication.Status.PUBLISHED:
            return attrs

        content = attrs.get("content", getattr(self.instance, "content", ""))
        preview = attrs.get("preview", getattr(self.instance, "preview", ""))
        errors = {}
        if not _has_visible_html_text(content):
            errors["content"] = "This field may not be blank when publishing."
        if not _has_visible_html_text(preview):
            errors["preview"] = "This field may not be blank when publishing."
        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def update(self, instance, validated_data):
        if "keywords" in validated_data:
            instance.keywords = validated_data.pop("keywords")
        return super().update(instance, validated_data)

    def create(self, validated_data):
        # Tagulous commits tags through a m2m table, so the row has to exist
        # before the assignment can be saved -- hence the second save().
        keywords = validated_data.pop("keywords", None)
        instance = super().create(validated_data)
        if keywords is not None:
            instance.keywords = keywords
            instance.save()
        return instance


class PublicationListManagementSerializer(PublicationManagementSerializer):
    class Meta(PublicationManagementSerializer.Meta):
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
    class ImagePathOrUploadField(serializers.ImageField):
        """
        Accept either an uploaded image file or a string path/URL.
        String values let admins manually edit existing DB image paths.
        """

        def to_internal_value(self, data):
            if isinstance(data, str):
                value = data.strip()
                if not value:
                    raise serializers.ValidationError("Image path cannot be empty.")
                return value
            return super().to_internal_value(data)

    image = ImagePathOrUploadField()

    class Meta:
        model = CarouselItem
        fields = ["id", "title", "url", "image", "ordering"]


class PartnerManagementSerializer(serializers.ModelSerializer):
    class LogoPathOrUploadField(serializers.ImageField):
        """
        Accept either an uploaded image file or a string path/URL.
        String values let admins manually edit existing DB logo paths.
        """

        def to_internal_value(self, data):
            if isinstance(data, str):
                value = data.strip()
                if not value:
                    raise serializers.ValidationError("Logo path cannot be empty.")
                return value
            return super().to_internal_value(data)

    logo = LogoPathOrUploadField()

    class Meta:
        model = Partner
        fields = ["id", "name", "url", "logo", "ordering"]
