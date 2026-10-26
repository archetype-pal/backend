from rest_framework import serializers

from .models import RESERVED_HEADING_SLUGS, RESERVED_SLUGS, MenuHeading, Page


class MenuHeadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuHeading
        fields = ["id", "slug", "title", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_slug(self, value):
        # The nav order refers to a heading by slug, so renaming it would
        # silently drop the heading's position.
        if self.instance is not None and value != self.instance.slug:
            raise serializers.ValidationError("A menu heading's slug cannot be changed.")
        if value in RESERVED_HEADING_SLUGS:
            raise serializers.ValidationError(f"'{value}' is reserved for a built-in menu heading.")
        return value


class PageSerializer(serializers.ModelSerializer):
    menu_heading = serializers.SlugRelatedField(
        slug_field="slug", queryset=MenuHeading.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Page
        fields = [
            "id",
            "slug",
            "title",
            "content",
            "status",
            "menu_heading",
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
    menu_heading = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Page
        fields = ["id", "slug", "title", "status", "menu_heading", "order", "include_in_quick_link", "updated_at"]
