"""Small text helpers shared across apps."""

import re

_WHITESPACE_RE = re.compile(r"\s+")


def collapse_whitespace(value: str) -> str:
    """Runs of whitespace become one space; both ends are trimmed."""
    return _WHITESPACE_RE.sub(" ", value).strip()
