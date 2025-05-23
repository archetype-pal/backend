from admin_ordering.admin import OrderableAdmin
from django.contrib import admin
import tagulous.admin

from .models import CarouselItem, Comment, Event, Publication


@admin.register(CarouselItem)
class CarouselItemAdmin(OrderableAdmin, admin.ModelAdmin):
    list_display = ["title", "ordering"]
    fields = ["title", "url", "image"]
    list_editable = ["ordering"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "created_at")
    search_fields = ["title"]
    prepopulated_fields = {"slug": ("title",)}

    readonly_fields = ("created_at", "updated_at")


class PublicationAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "status", "keywords", "created_at")
    list_filter = ("status", "is_blog_post", "is_news", "is_featured", "allow_comments")
    search_fields = ("title", "content")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("similar_posts",)
    fieldsets = (
        ("Publication Details", {"fields": ("title", "slug", "content", "preview", "author")}),
        (
            "Publication Options",
            {"fields": ("status", "published_at", "is_blog_post", "is_news", "is_featured", "allow_comments")},
        ),
        ("SEO", {"fields": ("similar_posts", "keywords")}),
    )

    readonly_fields = ("created_at", "updated_at")

    def get_form(self, request, obj=None, **kwargs):
        # Overriden to prepopulate the author field with the current user
        form = super().get_form(request, obj, **kwargs)
        if not obj:  # Only prepopulate for new publications
            form.base_fields["author"].initial = request.user
        return form


tagulous.admin.register(Publication, PublicationAdmin)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "author_name", "author_email", "is_approved", "created_at")
    search_fields = ["author_name", "author_email", "content"]
    list_filter = ["created_at", "is_approved"]
