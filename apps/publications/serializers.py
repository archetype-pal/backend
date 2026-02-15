from rest_framework import serializers

from apps.publications.models import CarouselItem, Comment, Event, Publication
from apps.users.serializers import UserSummarySerializer


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

    number_of_comments = serializers.SerializerMethodField()

    def get_number_of_comments(self, publication):
        return publication.comments.filter(is_approved=True).count()

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
        approved_comments = Comment.objects.filter(post=obj, is_approved=True)
        return CommentSerializer(approved_comments, many=True).data

    class Meta:
        model = Publication
        fields = PublicationListSerializer.Meta.fields + ["content", "comments"]
