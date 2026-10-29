"""TEI XML → `data-dpt` HTML (reverse direction).

Inverse of `data_dpt_to_tei`. TEI elements in the mapping are rebuilt as
`data-dpt` spans with the original attribute order (`data-dpt`,
`data-dpt-cat`, `data-dpt-type`, `data-dpt-src`, `data-graph-id`); `cat` is
derived from the element. All other nodes are re-emitted byte-for-byte.
"""

from typing import Any

from .mapping import DPT_CAT, GRAPH_ID_PREFIX, TEI_TO_DPT, escape_attr, render_attrs
from .rewriters import BufferedRewriter, Scanner


def _corresp_to_graph_ids(raw: str) -> str:
    ids: list[str] = []
    for token in raw.split():
        token = token.lstrip("#")
        if token.startswith(GRAPH_ID_PREFIX):
            ids.append(token[len(GRAPH_ID_PREFIX) :])
    return ",".join(ids)


class _TeiToDptRewriter(BufferedRewriter):
    def render_node(self, node: dict[str, Any]) -> str:
        return _render_reverse(node)


def _render_reverse(node: dict[str, Any]) -> str:
    tag = node["tag"]
    inner = "".join(node["parts"])

    dpt = TEI_TO_DPT.get(tag)
    if dpt is None:
        return f"<{tag}{render_attrs(node['attrs'])}>{inner}</{tag}>"

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
    return _TeiToDptRewriter().run(content).result()


class _TeiElementFinder(Scanner):
    """Detect whether any element in the mapping is present."""

    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in TEI_TO_DPT:
            self.found = True


def contains_tei_element(content: str) -> bool:
    """True when `content` holds at least one element the mapping treats as TEI.

    Positive identification of TEI, as opposed to "the reverse converter would
    re-render this differently" — which is also true of plain HTML whose
    attribute quoting merely gets normalised, and so misclassifies unmigrated
    rows as already-migrated.
    """
    return _TeiElementFinder().run(content).found
