"""TEI XML → `data-dpt` HTML (Phase H.2, reverse direction).

Inverse of `data_dpt_to_tei`. TEI elements in the mapping are rebuilt as
`data-dpt` spans with the original attribute order (`data-dpt`,
`data-dpt-cat`, `data-dpt-type`, `data-dpt-src`, `data-graph-id`); `cat` is
derived from the element. All other nodes are re-emitted byte-for-byte.
"""

from html.parser import HTMLParser
from typing import Any

from .mapping import DPT_CAT, GRAPH_ID_PREFIX, TEI_TO_DPT, escape_attr


def _corresp_to_graph_ids(raw: str) -> str:
    ids: list[str] = []
    for token in raw.split():
        token = token.lstrip("#")
        if token.startswith(GRAPH_ID_PREFIX):
            ids.append(token[len(GRAPH_ID_PREFIX) :])
    return ",".join(ids)


class _TeiToDptRewriter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._root: dict[str, Any] = {"parts": []}
        self._stack: list[dict[str, Any]] = [self._root]

    def _append(self, text: str) -> None:
        self._stack[-1]["parts"].append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack.append({"tag": tag, "attrs": attrs, "parts": []})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._append(f"<{tag}{_render_attrs(attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        if len(self._stack) == 1:
            return
        node = self._stack.pop()
        self._append(_render_reverse(node))

    def handle_data(self, data: str) -> None:
        self._append(data)

    def handle_entityref(self, name: str) -> None:
        self._append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._append(f"<!{decl}>")

    def get_html(self) -> str:
        return "".join(self._root["parts"])


def _render_attrs(attrs: list[tuple[str, str | None]]) -> str:
    out: list[str] = []
    for key, value in attrs:
        out.append(f" {key}" if value is None else f' {key}="{escape_attr(value)}"')
    return "".join(out)


def _render_reverse(node: dict[str, Any]) -> str:
    tag = node["tag"]
    inner = "".join(node["parts"])

    dpt = TEI_TO_DPT.get(tag)
    if dpt is None:
        return f"<{tag}{_render_attrs(node['attrs'])}>{inner}</{tag}>"

    attr_map = {key: (value or "") for key, value in node["attrs"]}
    out: list[tuple[str, str]] = [("data-dpt", dpt)]

    if dpt == "lb":
        if attr_map.get("type") == "sep":
            out.append(("data-dpt-cat", "sep"))
    else:
        out.append(("data-dpt-cat", DPT_CAT[dpt]))
        if attr_map.get("type"):
            out.append(("data-dpt-type", attr_map["type"]))

    if attr_map.get("source"):
        out.append(("data-dpt-src", attr_map["source"]))
    if attr_map.get("corresp"):
        out.append(("data-graph-id", _corresp_to_graph_ids(attr_map["corresp"])))

    rendered = "".join(f' {key}="{escape_attr(value)}"' for key, value in out)
    return f"<span{rendered}>{inner}</span>"


def tei_to_data_dpt(content: str) -> str:
    parser = _TeiToDptRewriter()
    parser.feed(content or "")
    parser.close()
    return parser.get_html()
