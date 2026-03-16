import csv
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import json
import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


@dataclass(frozen=True)
class ElementSpec:
    tag: str
    type_name: str | None
    text_hint: str | None


def parse_elementid(elementid_raw: str) -> ElementSpec:
    """
    Parse legacy elementid JSON payload into a matching specification.

    Expected shape:
      [["", "clause"], ["type", "salutation"], ["@text", "salutem"]]
    """
    try:
        payload = json.loads(elementid_raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - exercised via tests
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

    type_name = (pairs.get("type") or "").strip() or None
    text_hint = (pairs.get("@text") or "").strip() or None

    return ElementSpec(tag=tag, type_name=type_name, text_hint=text_hint)


def _parse_annotation_ids(raw: str) -> list[str]:
    values = [part.strip() for part in raw.split(",")]
    return [value for value in values if value]


class _SpanAnnotationRewriter(HTMLParser):
    def __init__(self, spec: ElementSpec, annotation_id: int) -> None:
        super().__init__(convert_charrefs=False)
        self.spec = spec
        self.annotation_id = str(annotation_id)
        self._root: dict[str, Any] = {"parts": []}
        self._stack: list[dict[str, Any]] = [self._root]
        self.matched_spans = 0
        self.changed_spans = 0

    def _current(self) -> dict[str, Any]:
        return self._stack[-1]

    def _append(self, text: str) -> None:
        self._current()["parts"].append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = {"tag": tag, "attrs": attrs, "parts": [], "text_parts": []}
        self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if len(self._stack) == 1:
            return
        node = self._stack.pop()
        rendered = self._render_node(node, closed_tag=tag)
        self._append(rendered)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._append(self._render_start_tag(tag, attrs, close_as_empty=True))

    def handle_data(self, data: str) -> None:
        self._append(data)
        self._current().setdefault("text_parts", []).append(data)

    def handle_entityref(self, name: str) -> None:
        self._append(f"&{name};")
        self._current().setdefault("text_parts", []).append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append(f"&#{name};")
        self._current().setdefault("text_parts", []).append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._append(f"<!{decl}>")

    def unknown_decl(self, data: str) -> None:
        self._append(f"<![{data}]>")

    def get_html(self) -> str:
        return "".join(self._root["parts"])

    def _render_attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        rendered: list[str] = []
        for key, value in attrs:
            if value is None:
                rendered.append(f" {key}")
            else:
                rendered.append(f' {key}="{escape(value, quote=True)}"')
        return "".join(rendered)

    def _render_start_tag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        close_as_empty: bool = False,
    ) -> str:
        suffix = "/>" if close_as_empty else ">"
        return f"<{tag}{self._render_attrs(attrs)}{suffix}"

    def _render_node(self, node: dict[str, Any], closed_tag: str) -> str:
        tag = node["tag"]
        attrs = list(node["attrs"])
        text_value = _normalize_text("".join(node.get("text_parts", [])))

        if tag == "span" and self._should_match(attrs, text_value):
            self.matched_spans += 1
            attrs, changed = self._ensure_annotation_id(attrs)
            if changed:
                self.changed_spans += 1

        open_tag = self._render_start_tag(tag, attrs)
        inner = "".join(node["parts"])
        close_tag = f"</{closed_tag}>"
        return f"{open_tag}{inner}{close_tag}"

    def _should_match(self, attrs: list[tuple[str, str | None]], span_text: str) -> bool:
        attr_map = {key: (value or "") for key, value in attrs}
        if attr_map.get("data-dpt", "") != self.spec.tag:
            return False
        if self.spec.type_name and attr_map.get("data-dpt-type", "") != self.spec.type_name:
            return False
        if self.spec.text_hint and _normalize_text(self.spec.text_hint) not in span_text:
            return False
        return True

    def _ensure_annotation_id(self, attrs: list[tuple[str, str | None]]) -> tuple[list[tuple[str, str | None]], bool]:
        attr_map = {key: value for key, value in attrs}
        existing_raw = attr_map.get("data-annotation-id") or ""
        existing_ids = _parse_annotation_ids(existing_raw)
        if self.annotation_id in existing_ids:
            return attrs, False

        merged = ",".join([*existing_ids, self.annotation_id]) if existing_ids else self.annotation_id

        updated: list[tuple[str, str | None]] = []
        replaced = False
        for key, value in attrs:
            if key == "data-annotation-id":
                updated.append((key, merged))
                replaced = True
            else:
                updated.append((key, value))
        if not replaced:
            updated.append(("data-annotation-id", merged))

        return updated, True


def embed_annotation_ids_in_content(content: str, spec: ElementSpec, annotation_id: int) -> tuple[str, int, int]:
    parser = _SpanAnnotationRewriter(spec=spec, annotation_id=annotation_id)
    parser.feed(content)
    parser.close()
    return parser.get_html(), parser.matched_spans, parser.changed_spans


class Command(BaseCommand):
    help = "Embed Graph annotation ids in manuscripts_imagetext.content using CSV element selectors."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--csv", dest="csv_path", type=str, required=True, help="Path to CSV file to process.")
        parser.add_argument(
            "--annotation-id",
            dest="annotation_id",
            type=int,
            required=False,
            help="Process only one annotation id.",
        )

        mode_group = parser.add_mutually_exclusive_group()
        mode_group.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes to the database.",
        )
        mode_group.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to database (default behavior).",
        )

    def handle(self, *args, **options) -> None:
        csv_path: str = options["csv_path"]
        only_annotation_id: int | None = options.get("annotation_id")
        apply_changes: bool = bool(options.get("apply"))

        summary = {
            "csv_rows_total": 0,
            "csv_rows_processed": 0,
            "csv_rows_invalid": 0,
            "rows_missing_graph": 0,
            "rows_missing_imagetext": 0,
            "imagetext_rows_checked": 0,
            "imagetext_rows_with_matches": 0,
            "imagetext_rows_updated": 0,
            "matched_spans": 0,
            "updated_spans": 0,
        }

        self.stdout.write(
            f"Running in {'APPLY' if apply_changes else 'DRY-RUN'} mode against CSV: {csv_path}"
        )

        try:
            with open(csv_path, newline="", encoding="utf-8") as csv_file:
                reader = csv.DictReader(csv_file)
                headers = reader.fieldnames or []
                required_headers = {"id", "annotation_id", "elementid"}
                missing_headers = required_headers.difference(headers)
                if missing_headers:
                    raise CommandError(
                        f"Missing required CSV headers: {', '.join(sorted(missing_headers))}. "
                        "Expected: id, annotation_id, elementid."
                    )

                for row in reader:
                    summary["csv_rows_total"] += 1
                    row_annotation_raw = (row.get("annotation_id") or "").strip()
                    if not row_annotation_raw.isdigit():
                        summary["csv_rows_invalid"] += 1
                        continue

                    annotation_id = int(row_annotation_raw)
                    if only_annotation_id is not None and annotation_id != only_annotation_id:
                        continue

                    summary["csv_rows_processed"] += 1
                    elementid_raw = row.get("elementid") or ""
                    try:
                        spec = parse_elementid(elementid_raw)
                    except ValueError:
                        summary["csv_rows_invalid"] += 1
                        continue

                    graph = Graph.objects.filter(id=annotation_id).only("id", "item_image_id").first()
                    if graph is None:
                        summary["rows_missing_graph"] += 1
                        continue

                    image_texts = list(
                        ImageText.objects.filter(
                            item_image_id=graph.item_image_id,
                            type__in=[ImageText.Type.TRANSCRIPTION, ImageText.Type.TRANSLATION],
                        )
                    )
                    if not image_texts:
                        summary["rows_missing_imagetext"] += 1
                        continue

                    for image_text in image_texts:
                        summary["imagetext_rows_checked"] += 1
                        new_content, matched_spans, changed_spans = embed_annotation_ids_in_content(
                            image_text.content, spec, annotation_id
                        )
                        if matched_spans > 0:
                            summary["imagetext_rows_with_matches"] += 1
                            summary["matched_spans"] += matched_spans
                        if changed_spans > 0:
                            summary["updated_spans"] += changed_spans
                            summary["imagetext_rows_updated"] += 1
                            if apply_changes:
                                image_text.content = new_content
                                image_text.save()

        except FileNotFoundError as exc:
            raise CommandError(f"CSV file not found: {csv_path}") from exc

        self.stdout.write("--- Migration Summary ---")
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
