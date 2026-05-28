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

from .mapping import escape_attr

GID_PREFIX = "gid-"

# Elements that can carry a text↔region link: TEI phrase elements (lowercased
# by HTMLParser) and legacy data-dpt spans. Order in the document defines the
# index the link-write path addresses.
_TEI_LINKABLE = {"seg", "persname", "placename", "ex", "supplied", "lb"}

# HTMLParser folds tag names to lower case; these TEI elements are camelCase in
# the stored content, so any tag we re-emit (rather than pass through verbatim)
# must be restored to canonical case.
_CANONICAL_CASE = {"persname": "persName", "placename": "placeName"}


def _canon(tag: str) -> str:
    return _CANONICAL_CASE.get(tag, tag)


def _is_linkable(tag: str, attrs: dict[str, str]) -> bool:
    return tag in _TEI_LINKABLE or (tag == "span" and "data-dpt" in attrs)


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


class _LinkableCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if _is_linkable(tag, {k: (v or "") for k, v in attrs}):
            self.count += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def linkable_element_count(content: str) -> int:
    """How many link-capable elements *content* has (defines the link index)."""
    counter = _LinkableCounter()
    counter.feed(content or "")
    counter.close()
    return counter.count


class _RefAdder(HTMLParser):
    """Re-emit content verbatim, adding a graph ref to the index-th element."""

    def __init__(self, target_index: int, graph_id: int) -> None:
        super().__init__(convert_charrefs=False)
        self.target = target_index
        self.graph_id = graph_id
        self.out: list[str] = []
        self.seen = -1
        self.added = False

    def _emit_start(self, tag: str, attrs: list[tuple[str, str | None]], *, self_close: bool) -> None:
        d = {k: (v or "") for k, v in attrs}
        if _is_linkable(tag, d):
            self.seen += 1
            if self.seen == self.target:
                self.out.append(self._with_ref(tag, d, self_close=self_close))
                self.added = True
                return
        raw = self.get_starttag_text()
        self.out.append(raw if raw is not None else f"<{tag}>")

    def _with_ref(self, tag: str, d: dict[str, str], *, self_close: bool) -> str:
        if tag == "span" and "data-dpt" in d:
            existing = [p for p in d.get("data-graph-id", "").split(",") if p.strip()]
            if str(self.graph_id) not in existing:
                existing.append(str(self.graph_id))
            d = {**d, "data-graph-id": ",".join(existing)}
        else:
            tokens = d.get("corresp", "").split()
            token = f"#{GID_PREFIX}{self.graph_id}"
            if token not in tokens:
                tokens.append(token)
            d = {**d, "corresp": " ".join(tokens)}
        rendered = "".join(f' {k}="{escape_attr(v)}"' for k, v in d.items())
        return f"<{_canon(tag)}{rendered}{'/>' if self_close else '>'}"

    def handle_starttag(self, tag, attrs):
        self._emit_start(tag, attrs, self_close=False)

    def handle_startendtag(self, tag, attrs):
        self._emit_start(tag, attrs, self_close=True)

    def handle_endtag(self, tag):
        self.out.append(f"</{_canon(tag)}>")

    def handle_data(self, data):
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")

    def handle_comment(self, data):
        self.out.append(f"<!--{data}-->")


def add_graph_ref(content: str, element_index: int, graph_id: int) -> str:
    """Add a `corresp`/`data-graph-id` ref to the *element_index*-th linkable
    element. Raises IndexError if the index is out of range."""
    adder = _RefAdder(element_index, graph_id)
    adder.feed(content or "")
    adder.close()
    if not adder.added:
        raise IndexError(f"no linkable element at index {element_index}")
    return "".join(adder.out)


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
