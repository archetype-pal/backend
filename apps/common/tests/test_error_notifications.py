import logging
import sys
import types

from django.core import mail
from django.test import RequestFactory, override_settings
from django.utils.functional import SimpleLazyObject

from apps.common.error_notifications import AdminNotificationEmailHandler, AdminNotificationReporter

# Once MAILERS is defined, get_connection() reads it and ignores EMAIL_BACKEND —
# overriding the old setting here would silently stop capturing mail.
MAIL_ADMINS = override_settings(
    ADMINS=["ops@example.com"],
    MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}},
)


def unresolvable_user():
    raise RuntimeError("could not connect to server: Connection refused")


def build_reporter(request):
    try:
        raise ValueError("boom")
    except ValueError:
        return AdminNotificationReporter(request, *sys.exc_info())


def log_error(request):
    """Feed the handler what django.request would, without touching global logger state."""
    handler = AdminNotificationEmailHandler(
        include_html=True,
        reporter_class="apps.common.error_notifications.AdminNotificationReporter",
    )
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            __file__,
            0,
            "Internal Server Error: /api/v1/manuscripts/",
            None,
            sys.exc_info(),
        )
    record.status_code = 500
    record.request = request
    try:
        handler.handle(record)
    finally:
        handler.close()
    return record


def assert_one_degraded_email():
    """The retry path: admins still get the traceback, minus the request that broke rendering."""
    assert len(mail.outbox) == 1
    assert "Request data not supplied" in mail.outbox[0].body
    assert "Request Method" not in mail.outbox[0].body


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

    log_error(request)

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    html = mail.outbox[0].alternatives[0].content
    assert "Sanitized" in body and "Sanitized" in html
    assert "hunter2" not in body and "hunter2" not in html
    assert "unable to retrieve the current user" in body


@MAIL_ADMINS
def test_handler_survives_an_unparseable_body():
    request = RequestFactory().post("/api/v1/manuscripts/", data="x", content_type="multipart/form-data")
    request.user = SimpleLazyObject(unresolvable_user)

    record = log_error(request)

    assert_one_degraded_email()
    assert record.request is request


@MAIL_ADMINS
@override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1)
def test_handler_survives_a_body_with_too_many_fields():
    request = RequestFactory().post("/api/v1/manuscripts/", data={"a": "1", "b": "2"})
    request.user = SimpleLazyObject(unresolvable_user)

    log_error(request)

    assert_one_degraded_email()


@MAIL_ADMINS
def test_handler_survives_files_that_cannot_be_reparsed():
    request = RequestFactory().post("/api/v1/manuscripts/", data={"a": "1"})

    class UnreadableFiles(dict):
        def items(self):
            raise RuntimeError("stream consumed")

    request._post = {}
    request._files = UnreadableFiles()

    log_error(request)

    assert_one_degraded_email()
