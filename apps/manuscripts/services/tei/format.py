"""Pretty-print a stored TEI fragment for editing.

`ImageText.content` is authored and migrated as a single unbroken line — 862 of
the corpus's 899 texts contain no newline at all — which makes the backoffice
Source view unreadable. This lays the fragment out without touching a single
character of its text.

**The safety rule.** TEI body content is *mixed*: `<seg>`, `<p>` and `<persName>`
hold element children and character data side by side, so the whitespace between
them is text. A conventional indenter (``ET.indent``) rewrites that whitespace
and silently changes what the page says — `<seg>Salutem</seg>.` becoming
`<seg>Salutem</seg>\\n.` renders as "Salutem ." with a space before the stop.

So this formatter only ever **replaces an existing whitespace run with a
newline + indent**. It never inserts whitespace where the source had none and
never removes a run entirely, which leaves the character data byte-identical
once whitespace is collapsed the way HTML collapses it. The one exception is
between block-level siblings (`<p>`), where no character data is adjacent.
`test_format.py` holds both invariants against the live corpus.

Line breaks land, in order of preference, before an `<lb/>` — the manuscript's
own line beginnings, so the source mirrors the folio — then at the last space
that fits the wrap column.
"""

import re

INDENT = "  "
WRAP_COLUMN = 100

# Raw-token scanner: we re-emit every tag exactly as written, so attributes,
# quoting and entity escaping survive untouched. Nothing here parses them.
_TOKEN_RE = re.compile(
    r"<!--.*?-->|<\?.*?\?>|"
    r"<(?P<close>/)?(?P<name>[A-Za-z][\w:.-]*)"
    r"(?P<attrs>(?:\s+[\w:.-]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'))?)*)"
    r"\s*(?P<self>/)?>",
    re.DOTALL,
)


class _Element:
    __slots__ = ("tag", "open_raw", "close_raw", "children")

    def __init__(self, tag: str, open_raw: str, close_raw: str = ""):
        self.tag = tag
        self.open_raw = open_raw
        self.close_raw = close_raw
        self.children: list = []  # str (character data) | _Element

    @property
    def block_safe(self) -> bool:
        """True when every join inside this element is already whitespace.

        Only then may children be broken onto their own lines: each newline
        replaces a run that was there, so no character data gains a space.
        Two elements written flush against each other (`</seg><lb …>`) fail
        this — separating them would insert a space into the text.
        """
        if not self.children:
            return False
        first, last = self.children[0], self.children[-1]
        if not (isinstance(first, str) and first.isspace()):
            return False
        if not (isinstance(last, str) and last.isspace()):
            return False
        previous_was_element = False
        for child in self.children:
            if isinstance(child, str):
                if child.strip():
                    return False
                previous_was_element = False
            else:
                if previous_was_element:
                    return False
                previous_was_element = True
        return True


def _parse(content: str) -> _Element | None:
    """Build a shallow tree of raw tokens, or None if the tags don't balance."""
    root = _Element("", "")
    stack = [root]
    pos = 0
    for m in _TOKEN_RE.finditer(content):
        if m.start() > pos:
            stack[-1].children.append(content[pos : m.start()])
        pos = m.end()
        raw = m.group(0)
        name = m.group("name")
        if name is None:  # comment or processing instruction
            stack[-1].children.append(_Element("", raw))
        elif m.group("self"):
            stack[-1].children.append(_Element(name, raw))
        elif m.group("close"):
            if len(stack) < 2 or stack[-1].tag != name:
                return None
            stack.pop().close_raw = raw
        else:
            node = _Element(name, raw)
            stack[-1].children.append(node)
            stack.append(node)
    if len(stack) != 1:
        return None
    if pos < len(content):
        root.children.append(content[pos:])
    return root


def _inline_tokens(node: _Element, out: list) -> None:
    """Flatten a mixed-content subtree to a stream of raw strings and markers.

    A whitespace run becomes ``None`` — a break opportunity the flow step may
    spend on a newline or spend on the original spacing, never on nothing.
    """
    for child in node.children:
        if isinstance(child, str):
            for part in re.split(r"(\s+)", child):
                if not part:
                    continue
                out.append(None if part.isspace() else part)
        else:
            if not child.children and not child.close_raw:
                out.append(("lb" if child.tag == "lb" else "tag", child.open_raw))
                continue
            out.append(("lb" if child.tag == "lb" else "tag", child.open_raw))
            _inline_tokens(child, out)
            out.append(("tag", child.close_raw))


def _flow(node: _Element, depth: int, width: int, start_col: int) -> str:
    """Lay mixed content out, spending only whitespace that is already there.

    Emits nothing between two tokens the source ran together, so character data
    can never gain a space; a run that *is* present becomes either one space or
    a newline + indent, both of which collapse identically.
    """
    tokens: list = []
    _inline_tokens(node, tokens)
    indent = INDENT * (depth + 1)
    out: list[str] = []
    col = start_col
    pending = False  # a whitespace run is waiting to be spent

    for tok in tokens:
        if tok is None:
            pending = True
            continue
        text = tok if isinstance(tok, str) else tok[1]
        # An <lb> marks a line beginning in the manuscript; start one here too.
        wants_line = isinstance(tok, tuple) and tok[0] == "lb"
        if pending:
            if col > len(indent) and (wants_line or col + 1 + len(text) > width):
                out.append("\n" + indent)
                col = len(indent)
            else:
                out.append(" ")
                col += 1
            pending = False
        out.append(text)
        col += len(text)
    if pending:
        out.append(" ")
    return "".join(out)


def _render(node: _Element, depth: int, width: int, col: int) -> str:
    """Block-indent element-only nodes; flow everything else in place.

    Only an element-only node may be broken across lines freely — it has no
    character data for the new whitespace to attach itself to.
    """
    if node.block_safe:
        inner = "".join(
            "\n" + INDENT * (depth + 1) + _render(child, depth + 1, width, len(INDENT) * (depth + 1))
            for child in node.children
            if isinstance(child, _Element)
        )
        return node.open_raw + inner + "\n" + INDENT * depth + node.close_raw
    return node.open_raw + _flow(node, depth, width, col + len(node.open_raw)) + node.close_raw


def format_tei(content: str, *, width: int = WRAP_COLUMN) -> str:
    """Return *content* laid out for reading, or unchanged if it can't be parsed.

    Malformed input is returned as given: the editor's validity badge already
    reports it, and mangling a fragment someone is midway through fixing would
    be worse than leaving it alone.
    """
    if not content or not content.strip():
        return content
    root = _parse(content)
    if root is None:
        return content
    # The top level is the one genuine block boundary: `ImageText.content` holds
    # <p> siblings, and whitespace between paragraphs belongs to neither. Any
    # character data out here, though, has no such boundary to hide a newline
    # behind, so the whole fragment flows as one run instead.
    if any(isinstance(c, str) and c.strip() for c in root.children):
        return _flow(root, -1, width, 0).strip()
    return "\n".join(_render(child, 0, width, 0) for child in root.children if isinstance(child, _Element))
