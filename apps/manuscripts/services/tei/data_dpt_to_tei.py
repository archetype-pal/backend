"""`data-dpt` HTML → TEI XML (Phase H.2, forward direction).

A buffered-node HTML rewriter: `data-dpt` spans are renamed to their TEI
element and re-attributed; every other node (text, entities, `<p>`, `<em>`,
`<a>`, plain `<span>`, `<br>`, comments) is re-emitted byte-for-byte. The
inverse is `tei_to_data_dpt`; round-trip fidelity is asserted in tests.
"""

from html import unescape
from html.parser import HTMLParser
from typing import Any

from .mapping import DPT_TO_TEI, GRAPH_ID_PREFIX, escape_attr

# Entities that are valid in XML and must stay escaped. Every other HTML named
# entity (&nbsp;, &aacute;, &thorn; …) is undefined in XML, so it is decoded to
# its literal character — part of turning HTML into well-formed TEI.
_XML_SAFE_ENTITIES = frozenset({"amp", "lt", "gt", "quot", "apos"})

# HTML void elements have no end tag; HTMLParser reports a bare `<br>` as a
# start tag, so without this the stack model would never close it. We emit them
# verbatim and never push them.
_VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


def _graph_ids_to_corresp(raw: str) -> str:
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    return " ".join(f"#{GRAPH_ID_PREFIX}{value}" for value in ids)


class _DptToTeiRewriter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._root: dict[str, Any] = {"parts": []}
        self._stack: list[dict[str, Any]] = [self._root]

    def _append(self, text: str) -> None:
        self._stack[-1]["parts"].append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_ELEMENTS:
            raw = self.get_starttag_text()
            self._append(raw if raw is not None else f"<{tag}{_render_attrs(attrs)}>")
            return
        self._stack.append({"tag": tag, "attrs": attrs, "parts": []})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing void elements (e.g. `<br />`) are not data-dpt spans, so
        # pass them through verbatim — re-synthesizing would drop original
        # whitespace like `<br />` → `<br/>` and break the round-trip.
        raw = self.get_starttag_text()
        self._append(raw if raw is not None else f"<{tag}{_render_attrs(attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        if len(self._stack) == 1:
            return
        node = self._stack.pop()
        self._append(_render_forward(node))

    def handle_data(self, data: str) -> None:
        self._append(data)

    def handle_entityref(self, name: str) -> None:
        if name in _XML_SAFE_ENTITIES:
            self._append(f"&{name};")
        else:
            # Known HTML entities decode to their character; unknown names are
            # returned unchanged by `unescape`, so nothing is silently dropped.
            self._append(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self._append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._append(f"<!{decl}>")

    def get_xml(self) -> str:
        # Flush any unclosed elements (malformed/truncated input) by emitting
        # their open tag + accumulated content into the parent, so text is never
        # silently dropped. The output stays as unbalanced as the input was —
        # the migration's round-trip check then skips such a row, and the
        # round-trip is lossless for well-formed input.
        while len(self._stack) > 1:
            node = self._stack.pop()
            open_tag = self._render_start_tag(node["tag"], node["attrs"])
            self._append(f"{open_tag}{''.join(node['parts'])}")
        return "".join(self._root["parts"])

    def _render_start_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        return f"<{tag}{_render_attrs(attrs)}>"


def _render_attrs(attrs: list[tuple[str, str | None]]) -> str:
    out: list[str] = []
    for key, value in attrs:
        out.append(f" {key}" if value is None else f' {key}="{escape_attr(value)}"')
    return "".join(out)


def _render_forward(node: dict[str, Any]) -> str:
    tag = node["tag"]
    attr_map = {key: (value or "") for key, value in node["attrs"]}
    inner = "".join(node["parts"])

    dpt = attr_map.get("data-dpt")
    if tag != "span" or not dpt or dpt not in DPT_TO_TEI:
        # Passthrough: re-emit exactly as parsed.
        return f"<{tag}{_render_attrs(node['attrs'])}>{inner}</{tag}>"

    tei_tag = DPT_TO_TEI[dpt]
    tei_attrs: list[tuple[str, str]] = []

    if dpt == "lb":
        if attr_map.get("data-dpt-src"):
            tei_attrs.append(("source", attr_map["data-dpt-src"]))
        if attr_map.get("data-dpt-cat") == "sep":
            tei_attrs.append(("type", "sep"))
    else:
        if attr_map.get("data-dpt-type"):
            tei_attrs.append(("type", attr_map["data-dpt-type"]))

    if attr_map.get("data-graph-id"):
        tei_attrs.append(("corresp", _graph_ids_to_corresp(attr_map["data-graph-id"])))

    rendered = "".join(f' {key}="{escape_attr(value)}"' for key, value in tei_attrs)
    return f"<{tei_tag}{rendered}>{inner}</{tei_tag}>"


def data_dpt_to_tei(content: str) -> str:
    parser = _DptToTeiRewriter()
    parser.feed(content or "")
    parser.close()
    return parser.get_xml()
