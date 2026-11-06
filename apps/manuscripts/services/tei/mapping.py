"""The locked `data-dpt` ↔ TEI mapping.

Grounded in the 25 distinct constructs that actually occur across the live
899-row corpus (not the generic roadmap table). Only `<span>` carries
`data-dpt`; every other element (`<p>`, `<em>`, `<a>`, plain `<span>`,
`<br>`) passes through untouched.

Design notes:
- `data-dpt-cat` is **derived** from the `data-dpt` value on the reverse
  trip (clause→words, everything else→chars), so it never needs separate
  storage. The lone `lb` with `cat="sep"` is the one exception and is carried
  on TEI as `@type="sep"`.
- `data-graph-id` (the text↔region link) is carried on TEI as
  `@corresp="#gid-N [#gid-M ...]"`, which round-trips multi-id spans.
- `lb` spans wrap a separator glyph in this corpus, so they are emitted as
  content-bearing `<lb>...</lb>` rather than empty milestones — fidelity over
  strict TEI purity at the converter layer (the ODD/validator decides schema
  shape later, in `validate.py`).
"""

from collections.abc import Iterable
from html import escape, unescape

# data-dpt value -> TEI element name.
DPT_TO_TEI: dict[str, str] = {
    "clause": "seg",
    "person": "persName",
    "place": "placeName",
    "ex": "ex",
    "supplied": "supplied",
    "lb": "lb",
}

# TEI element name -> data-dpt value (reverse). Keyed lowercase because the
# stdlib HTMLParser folds tag names to lower case, so `persName`/`placeName`
# arrive as `persname`/`placename` on the reverse trip.
TEI_TO_DPT: dict[str, str] = {tei.lower(): dpt for dpt, tei in DPT_TO_TEI.items()}

# HTMLParser-folded name -> canonical camelCase, for every TEI element a
# rewriter re-emits (rather than passes through verbatim).
CANONICAL_CASE: dict[str, str] = {tei.lower(): tei for tei in DPT_TO_TEI.values() if tei != tei.lower()}

# data-dpt value -> the data-dpt-cat it always carries in the corpus. `lb` is
# absent here because its category is special-cased (none, or "sep").
DPT_CAT: dict[str, str] = {
    "clause": "words",
    "person": "chars",
    "place": "chars",
    "ex": "chars",
    "supplied": "chars",
}

GRAPH_ID_PREFIX = "gid-"


def escape_attr(value: str) -> str:
    """Escape a value for a double-quoted attribute.

    Mirrors `html.escape(quote=True)` (escapes `& < > " '`). The corpus stores
    single quotes inconsistently in pasted-Word `style` attributes — most rows
    use the `&#x27;` entity (which this reproduces), but ImageText #646 uses
    raw `'`. Since `HTMLParser` decodes both forms to the same `'`, no single
    rule round-trips both; reproducing the common (`&#x27;`) form leaves #646
    as the sole non-round-tripping row, which `migrate_imagetext_to_tei`
    reports for manual review (it is corrupt Word markup
    already flagged for cleanup).
    """
    return escape(value, quote=True)


# HTML void elements have no end tag; HTMLParser reports a bare `<br>` as a
# start tag, so without this the rewriters' stack model would never close it.
# They are emitted verbatim and never pushed. Shared by both directional rewriters.
VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


def canonical_data_dpt(html: str) -> str:
    """Canonical form for comparing two `data-dpt` strings.

    The forward converter decodes HTML named entities (`&nbsp;`, `&aacute;`)
    to literal characters so the TEI is valid XML, so a round-trip is
    canonical-form equivalent rather than byte-identical for those rows.
    Every caller that verifies a round-trip (`migrate_imagetext_to_tei`,
    `verify_tei_cutover`) compares through this — otherwise entity spelling reads as
    data loss.
    """
    return unescape(html)


def render_attrs(attrs: Iterable[tuple[str, str | None]]) -> str:
    """Render parsed HTMLParser attrs (or an attribute dict's items) back to a tag's attribute string."""
    out: list[str] = []
    for key, value in attrs:
        out.append(f" {key}" if value is None else f' {key}="{escape_attr(value)}"')
    return "".join(out)
