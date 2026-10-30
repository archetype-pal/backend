from smtplib import SMTPAuthenticationError, SMTPServerDisconnected
from unittest import mock

from django.core.cache import cache
import pytest
from rest_framework import status

from apps.publications import tasks
from apps.publications.models import Comment
from apps.publications.services import send_pending_comment_email
from apps.publications.tests.factories import CommentFactory, PublicationFactory
from apps.users.tests.factories import SuperuserFactory, UserFactory

SETTING_URL = "/api/v1/media/management/comments/email-setting/"


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    cache.clear()


@pytest.fixture(autouse=True)
def _send_emails_inline(monkeypatch):
    monkeypatch.setattr(tasks.email_pending_comment, "delay", tasks.email_pending_comment)


def _post_comment(client, post):
    return client.post(
        f"/api/v1/media/publications/{post.slug}/comments/",
        {"author_name": "Ann O'Brien", "content": "Fish & chips, isn't it?"},
        format="json",
    )


@pytest.mark.django_db
def test_a_comment_awaiting_approval_is_emailed_to_the_active_superusers(
    api_client, mailoutbox, django_capture_on_commit_callbacks, settings
):
    settings.FRONTEND_URL = "https://archetype.example/"
    post = PublicationFactory(title="Scribes & hands")
    superuser = SuperuserFactory(email="boss@example.org")
    left_out = [UserFactory(is_staff=True, email="staff@example.org"), SuperuserFactory(is_active=False)]
    SuperuserFactory(email="")

    with django_capture_on_commit_callbacks(execute=True):
        res = _post_comment(api_client, post)

    assert res.status_code == status.HTTP_201_CREATED
    [email] = mailoutbox
    assert email.to == []  # bcc: no superuser sees the others' addresses
    assert superuser.email in email.bcc
    assert not {user.email for user in left_out} & set(email.bcc)
    assert "" not in email.bcc
    assert email.subject == f"{settings.EMAIL_SUBJECT_PREFIX}New comment awaiting approval on “Scribes & hands”"
    assert "Ann O'Brien left a comment" in email.body
    assert "Fish & chips, isn't it?" in email.body
    assert f"https://archetype.example/backoffice/comments?post={post.pk}" in email.body


@pytest.mark.django_db
def test_a_signed_in_comment_awaiting_approval_is_emailed_too(
    api_client, mailoutbox, django_capture_on_commit_callbacks
):
    api_client.force_authenticate(UserFactory(is_staff=True))

    with django_capture_on_commit_callbacks(execute=True):
        _post_comment(api_client, PublicationFactory())

    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_a_superuser_comment_sends_no_email(api_client, mailoutbox, django_capture_on_commit_callbacks):
    api_client.force_authenticate(SuperuserFactory())

    with django_capture_on_commit_callbacks(execute=True):
        _post_comment(api_client, PublicationFactory())

    assert mailoutbox == []


@pytest.mark.django_db
def test_a_comment_is_still_saved_when_its_email_cannot_be_queued(
    api_client, django_capture_on_commit_callbacks, monkeypatch
):
    post = PublicationFactory()
    monkeypatch.setattr(tasks.email_pending_comment, "delay", mock.Mock(side_effect=ConnectionError("queue down")))

    with django_capture_on_commit_callbacks(execute=True):
        res = _post_comment(api_client, post)

    assert res.status_code == status.HTTP_201_CREATED
    assert Comment.objects.filter(post=post).exists()


@pytest.mark.django_db
def test_an_email_that_fails_to_send_is_tried_again():
    SuperuserFactory()
    comment = CommentFactory(is_approved=False)

    with mock.patch(
        "django.core.mail.EmailMessage.send", side_effect=[SMTPServerDisconnected("relay down"), 1]
    ) as send:
        tasks.email_pending_comment.apply(args=[comment.pk])

    assert send.call_count == 2


@pytest.mark.django_db
def test_an_email_the_relay_refuses_is_not_tried_again():
    SuperuserFactory()
    comment = CommentFactory(is_approved=False)

    with mock.patch(
        "django.core.mail.EmailMessage.send", side_effect=SMTPAuthenticationError(535, b"bad login")
    ) as send:
        result = tasks.email_pending_comment.apply(args=[comment.pk])

    assert send.call_count == 1
    assert result.failed()


@pytest.mark.django_db
def test_a_title_spanning_lines_still_makes_a_valid_subject(mailoutbox, settings):
    SuperuserFactory()
    comment = CommentFactory(is_approved=False, post=PublicationFactory(title="Charters\nof  Fife"))

    send_pending_comment_email(comment.pk)

    [email] = mailoutbox
    assert email.subject == f"{settings.EMAIL_SUBJECT_PREFIX}New comment awaiting approval on “Charters of Fife”"
    assert "“Charters of Fife”" in email.body


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["approved", "deleted", "missing"])
def test_no_email_for_a_comment_that_no_longer_waits(state, mailoutbox):
    SuperuserFactory()
    comment = CommentFactory(is_approved=state == "approved", is_deleted=state == "deleted")
    comment_id = comment.pk
    if state == "missing":
        comment.delete()

    send_pending_comment_email(comment_id)

    assert mailoutbox == []


@pytest.mark.django_db
def test_a_superuser_who_turns_the_emails_off_no_longer_gets_them(
    management_client, management_user, api_client, mailoutbox, django_capture_on_commit_callbacks
):
    other = SuperuserFactory()

    assert management_client.get(SETTING_URL).data == {"email_enabled": True}
    assert management_client.patch(SETTING_URL, {"email_enabled": False}, format="json").data == {
        "email_enabled": False
    }
    assert management_client.get(SETTING_URL).data == {"email_enabled": False}
    with django_capture_on_commit_callbacks(execute=True):
        _post_comment(api_client, PublicationFactory())

    [email] = mailoutbox
    assert other.email in email.bcc
    assert management_user.email not in email.bcc


@pytest.mark.django_db
def test_a_superuser_can_turn_the_emails_back_on(management_client):
    management_client.patch(SETTING_URL, {"email_enabled": False}, format="json")

    res = management_client.patch(SETTING_URL, {"email_enabled": True}, format="json")

    assert res.data == {"email_enabled": True}
    assert management_client.get(SETTING_URL).data == {"email_enabled": True}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch"])
def test_only_superusers_can_see_or_change_the_email_setting(authenticated_client, method):
    res = getattr(authenticated_client, method)(SETTING_URL, {"email_enabled": False}, format="json")

    assert res.status_code == status.HTTP_403_FORBIDDEN
