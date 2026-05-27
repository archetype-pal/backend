"""Wrap a converted TEI body fragment in a minimal, valid TEI P5 document.

`ImageText.content` holds a body-level fragment (`<p><seg>…`), so a standalone
`.tei` download needs a `<TEI>` envelope with a teiHeader to be openable in
TEI tools (OxGarage, Roma, TEI Publisher).
"""

from .mapping import escape_attr


def wrap_tei_document(body_xml: str, *, title: str, source_note: str) -> str:
    safe_title = escape_attr(title).replace("<", "&lt;").replace(">", "&gt;")
    safe_source = escape_attr(source_note).replace("<", "&lt;").replace(">", "&gt;")
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
