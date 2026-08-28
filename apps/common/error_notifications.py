"""Customization of Django's mail_admins error-notification email.

Swaps the default technical_500 templates for a shorter, colored report built
for reading in an inbox (no giant per-setting dump, traceback laid out with
the offending line highlighted), and trims the subject line down to what's
actually useful.
"""

from copy import copy
from pathlib import Path
import re

from django.utils.log import AdminEmailHandler
from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "mail_admins"


class _AdminNotificationFilter(SafeExceptionReporterFilter):
    """Cleanses by field name unconditionally, independent of DEBUG.

    Stock SafeExceptionReporterFilter only cleanses request.POST when a view
    opted in via @sensitive_post_parameters, and skips that (plus
    sensitive_variables) entirely once DEBUG is True — fine for the
    interactive debug page, not for an email that now goes out regardless of
    DEBUG (see AdminNotificationEmailHandler).
    """

    cleansed_substitute = "Sanitized"

    def is_active(self, request):
        return True


class AdminNotificationReporter(ExceptionReporter):
    @property
    def html_template_path(self):
        return _TEMPLATE_DIR / "500.html"

    @property
    def text_template_path(self):
        return _TEMPLATE_DIR / "500.txt"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scoped to this reporter only, so the interactive DEBUG=True debug
        # page (which uses the project-wide DEFAULT_EXCEPTION_REPORTER_FILTER)
        # keeps showing raw values for local debugging.
        self.filter = _AdminNotificationFilter()

    def get_traceback_data(self):
        data = super().get_traceback_data()
        # Every configured Django setting, redacted or not — noise for triage
        # and the single biggest contributor to email length.
        data.pop("settings", None)

        if self.request is not None:
            # POST is only cleansed by Django for fields a view explicitly
            # flagged via @sensitive_post_parameters — catch password/token/
            # key/etc. fields by name on top of that. GET is left alone:
            # secrets don't belong in a query string in the first place, so
            # an endpoint putting them there is a bug to fix at the source,
            # not something to mask here.
            data["filtered_POST_items"] = [
                (k, self.filter.cleanse_setting(k, v)) for k, v in data["filtered_POST_items"]
            ]
            try:
                user = self.request.user
                data["user_id"] = user.pk if getattr(user, "is_authenticated", False) else None
            except Exception:
                data["user_id"] = None

        return data


class AdminNotificationEmailHandler(AdminEmailHandler):
    """AdminEmailHandler without the "(EXTERNAL IP)"/"(internal IP)" subject tag.

    That distinction only means something once INTERNAL_IPS is populated;
    left at its Django default (empty), every request is EXTERNAL, so the tag
    is always the same and just adds noise to the subject line.
    """

    _ip_tag_re = re.compile(r" \((?:EXTERNAL|internal) IP\)")

    def format_subject(self, subject):
        return super().format_subject(self._ip_tag_re.sub("", subject))

    def emit(self, record):
        try:
            super().emit(record)
        except Exception:
            # The message is built before send_mail runs, so anything the reporter
            # can't read off the request drops the email entirely. Retry without
            # it; the record is shared with other handlers, so copy before strip.
            try:
                degraded = copy(record)
                if hasattr(degraded, "request"):
                    del degraded.request
                super().emit(degraded)
            except Exception:
                self.handleError(record)
