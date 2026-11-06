from smtplib import SMTPConnectError, SMTPServerDisconnected

from celery import shared_task

# Only failures that a later attempt can fix: a relay that is down or
# dropped the connection. A refused login or recipient stays failed.
_TRANSIENT_SMTP_ERRORS = (SMTPConnectError, SMTPServerDisconnected, ConnectionError, TimeoutError)


@shared_task(
    autoretry_for=_TRANSIENT_SMTP_ERRORS, max_retries=3, retry_backoff=True, retry_backoff_max=60, retry_jitter=True
)
def email_pending_comment(comment_id: int) -> None:
    from apps.publications.services import send_pending_comment_email

    send_pending_comment_email(comment_id)
