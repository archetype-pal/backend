from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django_tagulous.utils import parse_tags
from rest_framework import serializers

from apps.common.serializers import UserSummarySerializer
from apps.publications.models import CarouselItem, Comment, Event, Partner, Publication
from apps.publications.services import author_display_name, public_comment_thread


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


class EventDetailSerializer(EventListSerializer):
    class Meta(EventListSerializer.Meta):
        fields = [*EventListSerializer.Meta.fields, "content"]


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
        fields = ["id", "parent", "author_name", "content", "created_at"]


class PublicThreadCommentSerializer(CommentSerializer):
    def to_representation(self, instance):
        if not instance.is_approved:
            return {"id": instance.pk, "parent": instance.parent_id, "removed": True}
        return {**super().to_representation(instance), "removed": False}


class CreatedCommentSerializer(CommentSerializer):
    class Meta(CommentSerializer.Meta):
        fields = [*CommentSerializer.Meta.fields, "is_approved"]


class SignedInCommentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ["parent", "author_email", "content"]
        extra_kwargs = {"content": {"max_length": 10000}}

    def validate_parent(self, parent):
        if parent is not None and (parent.post_id != self.context["publication"].id or not parent.is_approved):
            raise serializers.ValidationError("Replies must answer an approved comment on this publication.")
        return parent


class PublicCommentCreateSerializer(SignedInCommentCreateSerializer):
    class Meta(SignedInCommentCreateSerializer.Meta):
        fields = ["parent", "author_name", "author_email", "content"]


class PublicationDetailSerializer(PublicationListSerializer):
    comments = serializers.SerializerMethodField()

    def get_comments(self, obj):
        comments = getattr(obj, "comments_prefetched", None)
        if comments is None:
            comments = list(Comment.objects.filter(post=obj).order_by("created_at"))
        return PublicThreadCommentSerializer(public_comment_thread(comments), many=True).data

    class Meta:
        model = Publication
        fields = PublicationListSerializer.Meta.fields + ["content", "allow_comments", "comments"]


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
        return author_display_name(obj.author)

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


class EventManagementSerializer(EventDetailSerializer):
    class Meta(EventDetailSerializer.Meta):
        fields = [*EventDetailSerializer.Meta.fields, "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class CommentEmailSettingSerializer(serializers.Serializer):
    email_enabled = serializers.BooleanField()


class CommentManagementSerializer(serializers.ModelSerializer):
    post_title = serializers.CharField(source="post.title", read_only=True)
    post_slug = serializers.CharField(source="post.slug", read_only=True)
    parent_author_name = serializers.CharField(source="parent.author_name", read_only=True, default=None)
    parent_content = serializers.CharField(source="parent.content", read_only=True, default=None)

    class Meta:
        model = Comment
        fields = [
            "id",
            "post",
            "post_title",
            "post_slug",
            "parent_author_name",
            "parent_content",
            "content",
            "author_name",
            "author_email",
            "author_website",
            "is_approved",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


def media_relative_path(value: str) -> str | None:
    """Reduce an image reference to the name an ImageField stores: a path relative to MEDIA_ROOT.

    The backoffice sends whatever it holds — the absolute URL the read serializer
    returned, the `/media/...` path its picker builds, or a bare relative name.
    Stored verbatim, the first two get MEDIA_URL prefixed again on output
    (`/media/media/carousel/x.jpg`), so every form is normalised here.

    An absolute URL is only ever a reference to our own media, so one whose path
    is not under MEDIA_URL yields None: an ImageField cannot serve another host,
    and stripping the host would quietly turn the link into a missing file.
    """
    media_prefix = urlsplit(settings.MEDIA_URL).path.strip("/")
    if value.startswith(("http://", "https://")):
        path = unquote(urlsplit(value).path).lstrip("/")
        if not media_prefix or not path.startswith(f"{media_prefix}/"):
            return None
        return path[len(media_prefix) + 1 :]
    value = unquote(value).lstrip("/")
    if media_prefix and value.startswith(f"{media_prefix}/"):
        value = value[len(media_prefix) + 1 :]
    return value


class ImagePathOrUploadField(serializers.ImageField):
    """Accept either an uploaded image file or a string path/URL.

    String values let admins manually edit existing DB image paths (both
    `CarouselItem.image` and `Partner.logo` are plain ImageFields).
    """

    def to_internal_value(self, data):
        if isinstance(data, str):
            value = media_relative_path(data.strip())
            if value is None:
                raise serializers.ValidationError(f"Image URL must be under {settings.MEDIA_URL}.")
            if not value:
                raise serializers.ValidationError("Image path cannot be empty.")
            if ".." in value.split("/"):
                raise serializers.ValidationError("Image path cannot contain '..'.")
            return value
        return super().to_internal_value(data)


class CarouselItemManagementSerializer(CarouselItemSerializer):
    image = ImagePathOrUploadField()

    class Meta(CarouselItemSerializer.Meta):
        fields = ["id", *CarouselItemSerializer.Meta.fields, "ordering"]


class PartnerManagementSerializer(PartnerSerializer):
    logo = ImagePathOrUploadField()
