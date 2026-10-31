"""Test helper: run a management command and hand back what it printed."""

from io import StringIO

from django.core.management import call_command


def run_command(name: str, *args: str, **options) -> str:
    """Run `name` with `args`; stdout and stderr come back as one string."""
    out = StringIO()
    call_command(name, *args, stdout=out, stderr=out, **options)
    return out.getvalue()
