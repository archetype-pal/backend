"""Application services for publications app workflows."""

from django.db.models import Count, Prefetch, Q, QuerySet

from apps.publications.models import Comment, Publication


def get_public_publications_queryset(*, recent_posts: bool, action: str | None = None) -> QuerySet[Publication]:
    queryset = (
        Publication.objects.filter(status=Publication.Status.PUBLISHED)
        .select_related("author")
        .annotate(approved_comments_count=Count("comments", filter=Q(comments__is_approved=True)))
    )
    if action == "retrieve":
        queryset = queryset.prefetch_related(
            Prefetch(
                "comments",
                queryset=Comment.objects.filter(is_approved=True).only(
                    "id",
                    "post_id",
                    "content",
                    "author_name",
                    "created_at",
                ),
                to_attr="approved_comments_prefetched",
            )
        )
    if recent_posts:
        return queryset.order_by("-published_at")[:5]
    return queryset


def get_publication_management_queryset() -> QuerySet[Publication]:
    return Publication.objects.select_related("author").annotate(comment_count=Count("comments")).prefetch_related(
        "comments"
    )


def set_comment_approval(*, comment: Comment, is_approved: bool) -> Comment:
    comment.is_approved = is_approved
    comment.save(update_fields=["is_approved"])
    return comment
