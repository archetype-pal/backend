"""Dual-format catalogue descriptions, server side (docs/tei.md §4.5).

``HistoricalItemDescription.content`` holds EITHER legacy catalogue HTML — 703
rows of it, from outside sources — OR TEI prose whose people, places and
manuscripts are links into the corpus. One column, discriminated in band by a
**storage-owned wrapper element carrying the TEI namespace**.

This mirrors ``frontend/lib/tei-description.ts``. The duplication is deliberate
and small: the frontend owns the read/write path, the backend needs the same
answer for the ``.tei`` export, and a shared source would mean shipping either
Python to the browser or a round trip to classify a string. The invariant that
must hold across both is only this — *the discriminator is the TEI namespace on
a root ``<div>``, never a sniff for TEI element names*. Catalogue HTML is
arbitrary third-party markup, and a row that merely quotes ``<persName>`` in an
example must not be reinterpreted as markup.
"""

import re

TEI_NS = "http://www.tei-c.org/ns/1.0"

_OPEN_TAG_RE = re.compile(r"^<div(\s[^>]*?)?(/)?>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([\w:.-]+)\s*=\s*"([^"]*)"|([\w:.-]+)\s*=\s*'([^']*)'""")


def _open_tag(content: str):
    """Parse the value's leading ``<div …>``, or ``None`` when it has none."""
    match = _OPEN_TAG_RE.match(content)
    if not match:
        return None
    attrs = {}
    for name_dq, value_dq, name_sq, value_sq in _ATTR_RE.findall(match.group(1) or ""):
        if name_dq:
            attrs[name_dq.lower()] = value_dq
        else:
            attrs[name_sq.lower()] = value_sq
    return attrs, match.end(), match.group(2) == "/"


def is_tei_description(content: str) -> bool:
    """Whether this description is TEI rather than legacy HTML.

    Requires the TEI namespace on a ``<div>`` that is the value's *root* — it
    must both open the value and close it. A wrapper part-way through, or a plain
    HTML ``<div>`` (which legacy content routinely starts with), is not TEI.
    """
    trimmed = (content or "").strip()
    parsed = _open_tag(trimmed)
    if parsed is None:
        return False
    attrs, end, self_closing = parsed
    if attrs.get("xmlns") != TEI_NS:
        return False
    return len(trimmed) == end if self_closing else trimmed.endswith("</div>")


def tei_description_body(content: str) -> str | None:
    """The whole ``<div type="description">…</div>``, ready to embed in a document.

    Returns ``None`` for legacy HTML — callers skip those rather than converting
    them, because legacy content is not TEI and a document is not the place to
    start guessing.

    Returns the wrapper *including* its ``<div>``, unlike the frontend's
    ``teiDescriptionProse``: the editor needs the bare prose (the wrapper would
    be destroyed by its round-trip), whereas an export needs the element, which
    is what makes the prose a legal ``<text><body>`` resource.
    """
    if not is_tei_description(content):
        return None
    return content.strip()
