"""Customization of Django's mail_admins error-notification email.

Swaps the default technical_500 templates for a shorter, colored report built
for reading in an inbox (no giant per-setting dump, traceback laid out with
the offending line highlighted), and trims the subject line down to what's
actually useful.
"""

from pathlib import Path
import re

from django.utils.log import AdminEmailHandler
from django.views.debug import ExceptionReporter

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "mail_admins"


class AdminNotificationReporter(ExceptionReporter):
    @property
    def html_template_path(self):
        return _TEMPLATE_DIR / "500.html"

    @property
    def text_template_path(self):
        return _TEMPLATE_DIR / "500.txt"

    def get_traceback_data(self):
        data = super().get_traceback_data()
        # Every configured Django setting, redacted or not — noise for triage
        # and the single biggest contributor to email length.
        data.pop("settings", None)
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
