#!/usr/bin/env python3
"""Manually trigger the mail_admins error-notification email to verify it fires.

Usage (from the repo root):
    docker compose --env-file config/.env run --rm api python scripts/test_mail_admins.py

Requires DEBUG=false and at least one address in ADMIN_EMAILS in the active
env file (config/.env) — otherwise mail_admins is a no-op (see the
require_debug_false filter and ADMINS check in config/settings.py) and this
prints an explanation instead of an email.

With the default console EMAIL_BACKEND, the "sent" email is printed directly
to stdout (subject, recipients, full traceback, request info). Point
EMAIL_HOST/EMAIL_PORT/etc. at a real SMTP server (or a local catcher like
Mailpit) to see it land in an actual inbox instead.
"""

import os
from pathlib import Path
import sys


def _broken_view(request):
    raise ValueError("test_mail_admins.py: deliberate test exception")


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()

    from django.conf import settings
    from django.core.handlers.exception import convert_exception_to_response
    from django.test import RequestFactory

    if settings.DEBUG:
        print("DEBUG=true: mail_admins is disabled while DEBUG is on. Set DEBUG=false in config/.env and retry.")
        return
    if not settings.ADMINS:
        print("ADMINS is empty: set ADMIN_EMAILS in config/.env (comma-separated addresses) and retry.")
        return

    request = RequestFactory().get("/test-mail-admins/?foo=bar")
    response = convert_exception_to_response(_broken_view)(request)

    print(f"\nRaised a test exception (handler returned status {response.status_code}).")
    print(f"Recipients configured in ADMINS: {settings.ADMINS}")
    print(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
    print(
        "If that's the console backend, the full email is printed above this line."
        " Otherwise, check the inbox(es) listed above."
    )


if __name__ == "__main__":
    main()
