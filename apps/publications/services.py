"""Application services for publications app workflows."""

from django.conf import settings
from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.utils.html import linebreaks

from apps.publications.models import Comment, Publication

RECENT_POSTS_LIMIT: int = getattr(settings, "RECENT_POSTS_LIMIT", 5)


def get_public_publications_queryset(*, recent_posts: bool, action: str | None = None) -> QuerySet[Publication]:
    queryset = (
        Publication.objects.filter(status=Publication.Status.PUBLISHED)
        .select_related("author")
        # `keywords` is a m2m under the hood; without this every serialized row
        # costs its own query.
        .prefetch_related("keywords")
        .annotate(approved_comments_count=Count("comments", filter=Q(comments__is_approved=True)))
    )
    if action == "retrieve":
        queryset = queryset.prefetch_related(
            Prefetch(
                "comments",
                queryset=Comment.objects.filter(is_approved=True)
                .only(
                    "id",
                    "post_id",
                    "parent_id",
                    "content",
                    "author_name",
                    "created_at",
                )
                .order_by("created_at"),
                to_attr="approved_comments_prefetched",
            )
        )
    queryset = queryset.order_by(F("published_at").desc(nulls_last=True), "-id")
    if recent_posts:
        return queryset[:RECENT_POSTS_LIMIT]
    return queryset


def get_publication_management_queryset() -> QuerySet[Publication]:
    return (
        Publication.objects.select_related("author")
        .annotate(comment_count=Count("comments"))
        .prefetch_related("comments")
    )


def create_public_comment(
    *,
    publication: Publication,
    author_name: str,
    author_email: str,
    content: str,
    parent: Comment | None = None,
) -> Comment:
    comment: Comment = Comment.objects.create(
        post=publication,
        parent=parent,
        author_name=author_name,
        author_email=author_email,
        content=linebreaks(content, autoescape=True),
    )
    return comment
