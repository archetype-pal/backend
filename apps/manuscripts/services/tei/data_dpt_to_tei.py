"""`data-dpt` HTML → TEI XML (forward direction).

A buffered-node HTML rewriter: `data-dpt` spans are renamed to their TEI
element and re-attributed; every other node (text, entities, `<p>`, `<em>`,
`<a>`, plain `<span>`, `<br>`, comments) is re-emitted byte-for-byte. The
inverse is `tei_to_data_dpt`; round-trip fidelity is asserted in tests.
"""

from html import unescape
from typing import Any

from .mapping import DPT_TO_TEI, GRAPH_ID_PREFIX, render_attrs
from .rewriters import BufferedRewriter, attr_dict

# Entities that are valid in XML and must stay escaped. Every other HTML named
# entity (&nbsp;, &aacute;, &thorn; …) is undefined in XML, so it is decoded to
# its literal character — part of turning HTML into well-formed TEI.
_XML_SAFE_ENTITIES = frozenset({"amp", "lt", "gt", "quot", "apos"})


def _graph_ids_to_corresp(raw: str) -> str:
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    return " ".join(f"#{GRAPH_ID_PREFIX}{value}" for value in ids)


class _DptToTeiRewriter(BufferedRewriter):
    # Flush unclosed elements on malformed/truncated input so text is never
    # silently dropped; the migration's round-trip check then skips such a row.
    flush_unclosed = True

    def render_node(self, node: dict[str, Any]) -> str:
        return _render_forward(node)

    def handle_entityref(self, name: str) -> None:
        if name in _XML_SAFE_ENTITIES:
            self._emit(f"&{name};")
        else:
            # Known HTML entities decode to their character; unknown names are
            # returned unchanged by `unescape`, so nothing is silently dropped.
            self._emit(unescape(f"&{name};"))


def _render_forward(node: dict[str, Any]) -> str:
    tag = node["tag"]
    attr_map = attr_dict(node["attrs"])
    inner = "".join(node["parts"])

    dpt = attr_map.get("data-dpt")
    if tag != "span" or not dpt or dpt not in DPT_TO_TEI:
        # Passthrough: re-emit exactly as parsed.
        return f"<{tag}{render_attrs(node['attrs'])}>{inner}</{tag}>"

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

    return f"<{tei_tag}{render_attrs(tei_attrs)}>{inner}</{tei_tag}>"


def data_dpt_to_tei(content: str) -> str:
    return _DptToTeiRewriter().run(content).result()
