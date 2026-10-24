from celery import shared_task

from apps.publications.services import send_pending_comment_email


@shared_task(autoretry_for=(OSError,), retry_backoff=60)
def email_pending_comment(comment_id: int) -> None:
    send_pending_comment_email(comment_id)
