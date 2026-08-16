import logging
import sys
import types

from django.core import mail
from django.test import RequestFactory, override_settings
from django.utils.functional import SimpleLazyObject

from apps.common.error_notifications import AdminNotificationEmailHandler, AdminNotificationReporter

MAIL_ADMINS = override_settings(
    ADMINS=[("Ops", "ops@example.com")],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)


def unresolvable_user():
    raise RuntimeError("could not connect to server: Connection refused")


def build_reporter(request):
    try:
        raise ValueError("boom")
    except ValueError:
        return AdminNotificationReporter(request, *sys.exc_info())


def log_error(request):
    logger = logging.getLogger("tests.error_notifications")
    logger.handlers = [
        AdminNotificationEmailHandler(
            include_html=True,
            reporter_class="apps.common.error_notifications.AdminNotificationReporter",
        )
    ]
    logger.propagate = False
    try:
        raise ValueError("boom")
    except ValueError:
        logger.error(
            "Internal Server Error: /api/v1/manuscripts/",
            exc_info=sys.exc_info(),
            extra={"status_code": 500, "request": request},
        )


def test_reporter_survives_a_request_without_user():
    data = build_reporter(RequestFactory().get("/api/v1/manuscripts/")).get_traceback_data()

    assert data["user_id"] is None


def test_reporter_survives_a_user_that_raises():
    request = RequestFactory().get("/api/v1/manuscripts/")
    request.user = SimpleLazyObject(unresolvable_user)

    data = build_reporter(request).get_traceback_data()

    assert data["user_id"] is None
    assert "unable to retrieve" in data["user_str"]


def test_reporter_still_reports_an_authenticated_user():
    request = RequestFactory().get("/api/v1/manuscripts/")
    request.user = types.SimpleNamespace(is_authenticated=True, pk=7)

    data = build_reporter(request).get_traceback_data()

    assert data["user_id"] == 7


@MAIL_ADMINS
def test_handler_mails_when_the_user_cannot_be_resolved():
    request = RequestFactory().post("/api/v1/auth/token/login", {"password": "hunter2"})
    request.user = SimpleLazyObject(unresolvable_user)
    mail.outbox.clear()

    log_error(request)

    assert len(mail.outbox) == 1
    rendered = mail.outbox[0].body + str(mail.outbox[0].alternatives)
    assert "hunter2" not in rendered
    assert "unable to retrieve the current user" in rendered


@MAIL_ADMINS
def test_handler_survives_an_unparseable_body():
    request = RequestFactory().post("/api/v1/manuscripts/", data="x", content_type="multipart/form-data")
    request.user = SimpleLazyObject(unresolvable_user)

    log_error(request)


@MAIL_ADMINS
@override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1)
def test_handler_survives_a_body_with_too_many_fields():
    request = RequestFactory().post("/api/v1/manuscripts/", data={"a": "1", "b": "2"})
    request.user = SimpleLazyObject(unresolvable_user)

    log_error(request)
