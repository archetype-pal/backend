"""Wrap stored TEI fragments in minimal, valid TEI P5 documents.

Two envelopes, because the two kinds of fragment live in different places in a
TEI document:

* `wrap_tei_document` — `ImageText.content` holds a body-level fragment
  (`<p><seg>…`), so a standalone `.tei` download needs a `<TEI>` envelope with
  a teiHeader to be openable in TEI tools (OxGarage, Roma, TEI Publisher).
* `wrap_msdesc_document` — `MsDescArea.content` holds a *description* fragment
  (`<physDesc>…`), which belongs in `teiHeader/fileDesc/sourceDesc/msDesc`, not
  in `<text><body>` (TEI-descriptions Phase 8.1).
"""

from collections.abc import Mapping, Sequence

from .mapping import escape_attr
from .msdesc import MSDESC_AREAS


def _escape_text(value: str) -> str:
    """Escape a value for use as element text (`escape_attr` covers `& < > " '`)."""
    return escape_attr(value)


def wrap_tei_document(body_xml: str, *, title: str, source_note: str) -> str:
    safe_title = _escape_text(title)
    safe_source = _escape_text(source_note)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">\n'
        "  <teiHeader>\n"
        "    <fileDesc>\n"
        f"      <titleStmt><title>{safe_title}</title></titleStmt>\n"
        "      <publicationStmt><p>Archetype — Models of Authority</p></publicationStmt>\n"
        f"      <sourceDesc><p>{safe_source}</p></sourceDesc>\n"
        "    </fileDesc>\n"
        "  </teiHeader>\n"
        "  <text>\n"
        f"    <body>{body_xml}</body>\n"
        "  </text>\n"
        "</TEI>\n"
    )


def wrap_msdesc_document(
    areas: Mapping[str, str],
    *,
    title: str,
    source_note: str = "",
    descriptions: Sequence[str] = (),
) -> str:
    """Assemble msDesc area fragments into a standalone TEI P5 document.

    ``areas`` maps an ``MsDescArea.Area`` value to its stored fragment (already
    rooted at the same-named element). Areas missing from the mapping — or
    present but blank — are skipped, and the rest are emitted in the msDesc
    content-model order (``MSDESC_AREAS``), never the caller's iteration order:
    TEI fixes that order, while ``MsDescArea.Meta.ordering`` sorts areas
    alphabetically, so a queryset hands them over as history/msContents/
    msIdentifier/physDesc.

    Deliberately NOT ``wrap_tei_document``: the structured description lives in
    ``teiHeader/fileDesc/sourceDesc/msDesc``, so an ``<text><body>`` envelope
    would be the wrong home for it.

    ``descriptions`` are the linked-prose catalogue descriptions (docs/tei.md
    §4.5), each a ``<div type="description">`` — and THEY belong in
    ``<text><body>`` precisely because a ``div`` is a textstructure element, not
    a child of ``msDesc``. They therefore fill the resource a ``<TEI>`` root
    needs after the header; the empty ``<p/>`` stub is emitted only when there
    are none, mirroring ``msdesc-minimal/msdesc-minimal-template.xml`` ("The text
    element is required by TEI but may be empty for a catalogue-only record").

    Fragments are inserted verbatim (they are TEI already, and the root's
    default namespace declaration covers their unprefixed elements); only the
    caller-supplied ``title``/``source_note`` are escaped. An empty mapping
    yields an empty ``<msDesc>``, which is well-formed but not schema-valid
    (``msIdentifier`` is mandatory), so callers gate on emptiness rather than
    shipping a stub record.
    """
    safe_title = _escape_text(title)
    fragments = "".join(
        f"          {(areas.get(name) or '').strip()}\n" for name in MSDESC_AREAS if (areas.get(name) or "").strip()
    )
    # `fileDesc` admits exactly one `publicationStmt`, so the provenance note is
    # a second `<p>` inside it rather than a sibling statement.
    source_line = f"        <p>{_escape_text(source_note)}</p>\n" if source_note else ""
    prose = "".join(f"      {body.strip()}\n" for body in descriptions if body and body.strip())
    resource = prose if prose else "      <p/>\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">\n'
        "  <teiHeader>\n"
        "    <fileDesc>\n"
        f"      <titleStmt><title>{safe_title}</title></titleStmt>\n"
        "      <publicationStmt>\n"
        "        <p>Archetype — Models of Authority</p>\n"
        f"{source_line}"
        "      </publicationStmt>\n"
        "      <sourceDesc>\n"
        "        <msDesc>\n"
        f"{fragments}"
        "        </msDesc>\n"
        "      </sourceDesc>\n"
        "    </fileDesc>\n"
        "  </teiHeader>\n"
        "  <text>\n"
        "    <body>\n"
        f"{resource}"
        "    </body>\n"
        "  </text>\n"
        "</TEI>\n"
    )
