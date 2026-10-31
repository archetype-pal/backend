"""Base classes for the HTMLParser-driven rewriters over stored text markup.

Every converter and link helper in this package walks `ImageText.content`
with the stdlib `HTMLParser` and re-emits it byte-for-byte except for the one
construct it cares about. Two shapes cover all of them:

* `StreamingRewriter` — emits tokens as they arrive; only a *start tag* may be
  rewritten, by overriding `rewrite_start_tag`. Used for the text↔region link
  helpers, which add or strip an attribute on one element.
* `BufferedRewriter` — buffers each element with its children and renders it
  when its end tag arrives, by overriding `render_node`. Used for the
  data-dpt ↔ TEI converters, which rename elements and so need the whole
  node before they can emit anything.

Both are constructed with `convert_charrefs=False` so entities and character
references pass through as written instead of being decoded.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Self

from .mapping import CANONICAL_CASE, VOID_ELEMENTS, render_attrs

Attrs = list[tuple[str, str | None]]


def attr_dict(attrs: Attrs) -> dict[str, str]:
    """Parsed attrs as a dict, with valueless attributes (`<x disabled>`) as ``""``."""
    return {key: (value or "") for key, value in attrs}


class Scanner(HTMLParser):
    """An HTMLParser over stored markup that keeps entities as written (`convert_charrefs=False`)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)

    def run(self, content: str | None) -> Self:
        """Feed the whole `content` and return self, so callers can read the result and any counters."""
        self.feed(content or "")
        self.close()
        return self

    def _emit(self, text: str) -> None:
        """Where text and markup passed through as written go. A scanner that only reads drops it."""

    def handle_data(self, data: str) -> None:
        self._emit(data)

    def handle_entityref(self, name: str) -> None:
        self._emit(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._emit(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._emit(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._emit(f"<!{decl}>")


class StreamingRewriter(Scanner):
    """Re-emit content verbatim, giving subclasses one hook on each start tag.

    `rewrite_start_tag` returns the replacement tag text, or ``None`` to keep
    the original source text (so attribute quoting, spacing and case survive
    untouched on every element the subclass leaves alone).
    """

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []

    def _emit(self, text: str) -> None:
        self.out.append(text)

    def rewrite_start_tag(self, tag: str, attrs: dict[str, str], *, self_close: bool) -> str | None:
        raise NotImplementedError

    def _emit_start(self, tag: str, attrs: Attrs, *, self_close: bool) -> None:
        rewritten = self.rewrite_start_tag(tag, attr_dict(attrs), self_close=self_close)
        if rewritten is not None:
            self.out.append(rewritten)
            return
        raw = self.get_starttag_text()
        self.out.append(raw if raw is not None else f"<{tag}{render_attrs(attrs)}{'/>' if self_close else '>'}")

    def handle_starttag(self, tag: str, attrs: Attrs) -> None:
        self._emit_start(tag, attrs, self_close=False)

    def handle_startendtag(self, tag: str, attrs: Attrs) -> None:
        self._emit_start(tag, attrs, self_close=True)

    def handle_endtag(self, tag: str) -> None:
        self.out.append(f"</{self.canonical_tag(tag)}>")

    def canonical_tag(self, tag: str) -> str:
        """HTMLParser lower-cases tag names; a tag the rewriter re-emits gets its canonical case back."""
        return CANONICAL_CASE.get(tag, tag)

    def result(self) -> str:
        return "".join(self.out)


class BufferedRewriter(Scanner):
    """Buffer each element with its rendered children; subclasses render it on close.

    Void elements and self-closing tags are never buffered — they are passed
    through as written (re-synthesizing `<br />` as `<br/>` would break the
    round-trip). `render_node` receives ``{"tag", "attrs", "parts"}`` where
    ``parts`` are the already-rendered children, in order.

    `flush_unclosed` controls what happens to elements still open at the end
    of malformed input: ``True`` emits their open tag and content into the
    parent so no text is lost (the output stays as unbalanced as the input);
    ``False`` drops them.
    """

    flush_unclosed = False

    def __init__(self) -> None:
        super().__init__()
        self._root: dict[str, Any] = {"parts": []}
        self._stack: list[dict[str, Any]] = [self._root]

    def render_node(self, node: dict[str, Any]) -> str:
        raise NotImplementedError

    def _emit(self, text: str) -> None:
        self._stack[-1]["parts"].append(text)

    def handle_starttag(self, tag: str, attrs: Attrs) -> None:
        if tag in VOID_ELEMENTS:
            raw = self.get_starttag_text()
            self._emit(raw if raw is not None else f"<{tag}{render_attrs(attrs)}>")
            return
        self._stack.append({"tag": tag, "attrs": attrs, "parts": []})

    def handle_startendtag(self, tag: str, attrs: Attrs) -> None:
        raw = self.get_starttag_text()
        self._emit(raw if raw is not None else f"<{tag}{render_attrs(attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        if len(self._stack) == 1:
            return
        node = self._stack.pop()
        self._emit(self.render_node(node))

    def result(self) -> str:
        if self.flush_unclosed:
            while len(self._stack) > 1:
                node = self._stack.pop()
                self._emit(f"<{node['tag']}{render_attrs(node['attrs'])}>{''.join(node['parts'])}")
        return "".join(self._root["parts"])
