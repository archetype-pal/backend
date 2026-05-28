"""Text↔region link helpers over TEI content (text_annotation plan, Phase 1).

The link between a marked-up TEI element and an image region is an in-text
reference — `corresp="#gid-N"` on the element (and, on not-yet-migrated
content, `data-graph-id="N"` on a span) — pointing at a `Graph(annotation_type=
TEXT)` row. These helpers surface that relationship without a new model:

- `parse_graph_refs(content)` → the referenced Graph ids, with element context.
- `rewrite_graph_refs(content, mapping)` → renumber refs (e.g. after re-import).

Both accept either storage format (TEI or legacy data-dpt) and are pure.
"""

from dataclasses import dataclass
from html.parser import HTMLParser
import re

GID_PREFIX = "gid-"


@dataclass
class GraphRef:
    graph_ids: list[int]
    element: str
    type: str | None
    text: str = ""


def _ids_from_corresp(value: str) -> list[int]:
    out: list[int] = []
    for token in value.split():
        token = token.lstrip("#")
        if token.startswith(GID_PREFIX):
            token = token[len(GID_PREFIX) :]
        if token.isdigit():
            out.append(int(token))
    return out


def _ids_from_data_graph_id(value: str) -> list[int]:
    return [int(part) for part in value.split(",") if part.strip().isdigit()]


class _RefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.refs: list[GraphRef] = []
        # Stack of (ref_or_None, text_accumulator_index) per open element.
        self._stack: list[GraphRef | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        ids: list[int] = []
        if d.get("corresp"):
            ids = _ids_from_corresp(d["corresp"])
        elif d.get("data-graph-id"):
            ids = _ids_from_data_graph_id(d["data-graph-id"])
        if ids:
            ref = GraphRef(graph_ids=ids, element=tag, type=d.get("type") or d.get("data-dpt-type") or None)
            self.refs.append(ref)
            self._stack.append(ref)
        else:
            self._stack.append(None)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        # Attribute text to the nearest enclosing referenced element.
        for ref in reversed(self._stack):
            if ref is not None:
                ref.text += data
                break


def parse_graph_refs(content: str) -> list[GraphRef]:
    """Return every in-text graph reference with its element context."""
    parser = _RefCollector()
    parser.feed(content or "")
    parser.close()
    for ref in parser.refs:
        ref.text = re.sub(r"\s+", " ", ref.text).strip()
    return parser.refs


def referenced_graph_ids(content: str) -> set[int]:
    """Flat set of all Graph ids referenced from *content*."""
    ids: set[int] = set()
    for ref in parse_graph_refs(content):
        ids.update(ref.graph_ids)
    return ids


def rewrite_graph_refs(content: str, mapping: dict[int, int]) -> str:
    """Renumber graph references per *mapping* (old id → new id).

    Rewrites both `corresp="#gid-N"` and `data-graph-id="N[,M]"` forms; ids
    absent from *mapping* are left unchanged.
    """

    def repl_corresp(m: re.Match[str]) -> str:
        tokens = m.group(1).split()
        rebuilt: list[str] = []
        for token in tokens:
            bare = token.lstrip("#")
            if bare.startswith(GID_PREFIX) and bare[len(GID_PREFIX) :].isdigit():
                old = int(bare[len(GID_PREFIX) :])
                rebuilt.append(f"#{GID_PREFIX}{mapping.get(old, old)}")
            else:
                rebuilt.append(token)
        return f'corresp="{" ".join(rebuilt)}"'

    def repl_dgid(m: re.Match[str]) -> str:
        parts = [p.strip() for p in m.group(1).split(",")]
        rebuilt = [str(mapping.get(int(p), int(p))) if p.isdigit() else p for p in parts]
        return f'data-graph-id="{",".join(rebuilt)}"'

    content = re.sub(r'corresp="([^"]*)"', repl_corresp, content or "")
    content = re.sub(r'data-graph-id="([^"]*)"', repl_dgid, content)
    return content
