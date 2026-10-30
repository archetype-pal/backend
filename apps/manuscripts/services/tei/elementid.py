"""Resolve DigiPal `elementid` selectors back into in-text region links.

A DigiPal export records which transcription element a TEXT graph belongs to
on the *graph* side only, as `annotation.properties.elementid`, e.g.
``[["", "clause"], ["type", "address"], ["@text", "salutem"]]``: the data-dpt
element type, its sub-type, and a text hint. `embed_annotation_ids_in_content`
walks a `data-dpt` text and adds the graph's id to every matching span's
`data-graph-id`, which is the in-text form the rest of the application reads.

Used by migration 0027 (`embed_text_region_links`), which runs it for every
adopter at `migrate` time.
"""

from dataclasses import dataclass
import json
import re
from typing import Any

from .mapping import render_attrs
from .rewriters import Attrs, BufferedRewriter, attr_dict


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


@dataclass(frozen=True)
class ElementSpec:
    tag: str
    type_name: str | None
    text_hint: str | None


def parse_elementid(elementid_raw: str) -> ElementSpec:
    """Parse a legacy elementid JSON payload into a matching specification."""
    try:
        payload = json.loads(elementid_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("elementid is not valid JSON") from exc

    if not isinstance(payload, list) or not payload:
        raise ValueError("elementid must be a non-empty list")

    first = payload[0]
    if not isinstance(first, list) or len(first) != 2:
        raise ValueError("elementid first item must be a pair")

    tag = (first[1] or "").strip()
    if not tag:
        raise ValueError("elementid tag is missing")

    pairs: dict[str, str] = {}
    for entry in payload[1:]:
        if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str):
            pairs[entry[0]] = "" if entry[1] is None else str(entry[1])

    return ElementSpec(
        tag=tag,
        type_name=(pairs.get("type") or "").strip() or None,
        text_hint=(pairs.get("@text") or "").strip() or None,
    )


class _SpanAnnotationRewriter(BufferedRewriter):
    """Add `annotation_id` to the `data-graph-id` of every span matching `spec`."""

    def __init__(self, spec: ElementSpec, annotation_id: int) -> None:
        super().__init__()
        self.spec = spec
        self.annotation_id = str(annotation_id)
        self.matched_spans = 0
        self.changed_spans = 0

    # The text hint is matched against an element's own character data, so
    # keep that separately from the rendered children in `parts`.
    def _append_text(self, text: str) -> None:
        self._stack[-1].setdefault("text", []).append(text)

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        self._append_text(data)

    def handle_entityref(self, name: str) -> None:
        super().handle_entityref(name)
        self._append_text(f"&{name};")

    def handle_charref(self, name: str) -> None:
        super().handle_charref(name)
        self._append_text(f"&#{name};")

    def render_node(self, node: dict[str, Any]) -> str:
        tag = node["tag"]
        attrs: Attrs = list(node["attrs"])
        if tag == "span" and self._matches(attr_dict(attrs), _normalize_text("".join(node.get("text", [])))):
            self.matched_spans += 1
            attrs, changed = self._with_annotation_id(attrs)
            self.changed_spans += changed
        return f"<{tag}{render_attrs(attrs)}>{''.join(node['parts'])}</{tag}>"

    def _matches(self, attrs: dict[str, str], span_text: str) -> bool:
        if attrs.get("data-dpt", "") != self.spec.tag:
            return False
        if self.spec.type_name and attrs.get("data-dpt-type", "") != self.spec.type_name:
            return False
        return not self.spec.text_hint or _normalize_text(self.spec.text_hint) in span_text

    def _with_annotation_id(self, attrs: Attrs) -> tuple[Attrs, bool]:
        existing = [part.strip() for part in (attr_dict(attrs).get("data-graph-id") or "").split(",") if part.strip()]
        if self.annotation_id in existing:
            return attrs, False
        merged = ",".join([*existing, self.annotation_id])
        if "data-graph-id" in dict(attrs):
            return [(key, merged if key == "data-graph-id" else value) for key, value in attrs], True
        return [*attrs, ("data-graph-id", merged)], True


def embed_annotation_ids_in_content(content: str, spec: ElementSpec, annotation_id: int) -> tuple[str, int, int]:
    """Return ``(new_content, matched_spans, changed_spans)``."""
    parser = _SpanAnnotationRewriter(spec=spec, annotation_id=annotation_id).run(content)
    return parser.result(), parser.matched_spans, parser.changed_spans
