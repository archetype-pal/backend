"""TEI well-formedness validation (Phase H.10).

`ImageText.content` holds a body-level TEI fragment, so it's wrapped in an
inline root before parsing (the wrapper adds no newlines, so reported line
numbers match the input; only a line-1 column is offset by the prefix, which
we correct). Full TEI P5 schema (ODD/RNG) validation is a later addition;
catching malformed XML covers the common authoring mistakes.
"""

import xml.etree.ElementTree as ET

_WRAP_OPEN = "<__tei_validate_root__>"
_WRAP_CLOSE = "</__tei_validate_root__>"


def validate_tei_wellformed(content: str) -> list[dict]:
    """Return a list of well-formedness errors; empty means valid.

    Each error is ``{"line": int, "col": int, "message": str}`` (1-based line,
    0-based column, relative to the supplied content).
    """
    wrapped = f"{_WRAP_OPEN}{content or ''}{_WRAP_CLOSE}"
    try:
        ET.fromstring(wrapped)
        return []
    except ET.ParseError as exc:
        line, col = exc.position
        if line == 1:
            col = max(0, col - len(_WRAP_OPEN))
        message = str(exc)
        if ": line " in message:
            message = message.split(": line ")[0]
        return [{"line": line, "col": col, "message": message}]
