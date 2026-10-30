"""Application services for publications app workflows."""

from functools import partial
from html import unescape
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.utils.html import linebreaks, strip_tags
from django.utils.text import Truncator

from apps.publications.models import Comment, CommentEmailOptOut, Publication
from apps.publications.tasks import email_pending_comment

RECENT_POSTS_LIMIT = 5


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
                queryset=Comment.objects.only(
                    "id",
                    "post_id",
                    "parent_id",
                    "is_approved",
                    "content",
                    "author_name",
                    "created_at",
                ).order_by("created_at"),
                to_attr="comments_prefetched",
            )
        )
    queryset = queryset.order_by(F("published_at").desc(nulls_last=True), "-id")
    if recent_posts:
        return queryset[:RECENT_POSTS_LIMIT]
    return queryset


def get_publication_management_queryset() -> QuerySet[Publication]:
    return Publication.objects.select_related("author").annotate(
        comment_count=Count("comments", filter=Q(comments__is_deleted=False))
    )


def public_comment_thread(comments: list[Comment]) -> list[Comment]:
    by_id = {comment.pk: comment for comment in comments}
    shown: set[int] = set()
    for comment in comments:
        node = comment if comment.is_approved else None
        while node is not None and node.pk not in shown:
            shown.add(node.pk)
            node = by_id.get(node.parent_id) if node.parent_id is not None else None
    return [comment for comment in comments if comment.pk in shown]


@transaction.atomic
def delete_comment(comment: Comment) -> None:
    if not comment.replies.exists():
        parent = comment.parent
        comment.delete()
        # A placeholder only holds its replies' place, and is hidden from both the
        # thread and moderation, so once its last reply goes nobody could remove it.
        while parent is not None and parent.is_deleted and not parent.replies.exists():
            grandparent = parent.parent
            parent.delete()
            parent = grandparent
        return
    comment.author_name = ""
    comment.author_email = ""
    comment.author_website = None
    comment.content = ""
    comment.is_approved = False
    comment.is_deleted = True
    comment.save()


def create_public_comment(
    *,
    publication: Publication,
    author_name: str,
    content: str,
    author_email: str = "",
    parent: Comment | None = None,
    is_approved: bool = False,
) -> Comment:
    comment: Comment = Comment.objects.create(
        post=publication,
        parent=parent,
        author_name=author_name,
        author_email=author_email,
        content=linebreaks(content, autoescape=True),
        is_approved=is_approved,
    )
    if not is_approved:
        transaction.on_commit(partial(email_pending_comment.delay, comment.pk), robust=True)
    return comment


def author_display_name(user: Any) -> str | None:
    """How a user is credited on the public site: full name, else username, else nothing."""
    if not user:
        return None
    return user.get_full_name() or user.get_username() or None


def create_signed_in_comment(
    *, publication: Publication, user: Any, content: str, author_email: str = "", parent: Comment | None = None
) -> Comment:
    return create_public_comment(
        publication=publication,
        parent=parent,
        author_name=author_display_name(user) or "",
        author_email=user.email or author_email,
        content=content,
        is_approved=user.is_superuser,
    )


def send_pending_comment_email(comment_id: int) -> None:
    comment = Comment.objects.filter(pk=comment_id, is_approved=False, is_deleted=False).select_related("post").first()
    if comment is None:
        return
    recipients = list(
        get_user_model()
        .objects.filter(is_superuser=True, is_active=True, comment_email_opt_out__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return
    post = comment.post
    title = " ".join(post.title.split())  # a header must stay on one line
    excerpt = Truncator(unescape(strip_tags(comment.content.replace("<br>", "\n")))).chars(500)
    link = f"{settings.FRONTEND_URL.rstrip('/')}/backoffice/comments?post={post.pk}"
    # Bcc, so no superuser sees the others' addresses.
    EmailMessage(
        f"{settings.EMAIL_SUBJECT_PREFIX}New comment awaiting approval on “{title}”",
        f"{comment.author_name} left a comment on “{title}” that is awaiting approval:\n\n{excerpt}\n\n"
        f"Review it: {link}\n\nYou can turn these emails off on that page.\n",
        bcc=recipients,
    ).send()


def comment_emails_enabled(user: Any) -> bool:
    return not CommentEmailOptOut.objects.filter(user=user).exists()


def set_comment_emails(user: Any, enabled: bool) -> None:
    if enabled:
        CommentEmailOptOut.objects.filter(user=user).delete()
    else:
        CommentEmailOptOut.objects.get_or_create(user=user)
