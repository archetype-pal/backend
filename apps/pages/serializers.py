from rest_framework import serializers

from .models import RESERVED_SLUGS, Page


class PageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Page
        fields = [
            "id",
            "slug",
            "title",
            "content",
            "status",
            "order",
            "include_in_quick_link",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_slug(self, value):
        if value in RESERVED_SLUGS:
            raise serializers.ValidationError(f"'{value}' is reserved for a built-in about page.")
        return value


class PageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Page
        fields = ["id", "slug", "title", "status", "order", "include_in_quick_link", "updated_at"]
