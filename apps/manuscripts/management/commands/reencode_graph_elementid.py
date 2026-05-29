"""Phase H.5 — re-encode `Graph.annotation.properties.elementid`.

The legacy value is a `data-dpt` attribute tuple
(`[["", "person"], ["type", "name"], ["@text", "..."]]`) that nothing reads
now that the link runs element→graph via `corresp`/`data-graph-id`. This
re-encodes each TEXT graph's `elementid` to the **reverse** link — the
ImageText element(s) that reference it, with element/type/text context — which
is the selector data the W3C + IIIF layers (Track C) need. The legacy tuple is
preserved under `legacy_dpt_elementid`.

Default dry-run; `--apply` writes; `--reverse` restores the legacy tuple.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import parse_graph_refs


def build_reverse_map() -> dict[int, list[dict]]:
    """graph id → list of referencing elements across all ImageTexts."""
    reverse: dict[int, list[dict]] = defaultdict(list)
    for it in ImageText.objects.all().only("id", "type", "content"):
        for ref in parse_graph_refs(it.content or ""):
            for gid in ref.graph_ids:
                reverse[gid].append(
                    {
                        "image_text": it.id,
                        "kind": it.type,
                        "element": ref.element,
                        "type": ref.type,
                        "text": ref.text,
                    }
                )
    return reverse


class Command(BaseCommand):
    help = "Re-encode TEXT Graph.elementid to the reverse element link (Phase H.5)."

    def add_arguments(self, parser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Persist the re-encoding.")
        mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
        mode.add_argument("--reverse", action="store_true", help="Restore legacy_dpt_elementid.")

    def handle(self, *args, **options) -> None:
        if options.get("reverse"):
            self._reverse()
        else:
            self._forward(apply_changes=bool(options.get("apply")))

    def _forward(self, *, apply_changes: bool) -> None:
        reverse = build_reverse_map()
        summary = {"text_graphs": 0, "linked": 0, "unreferenced": 0, "written": 0}

        self.stdout.write(f"Running forward in {'APPLY' if apply_changes else 'DRY-RUN'} mode.")
        for graph in Graph.objects.filter(annotation_type="text").only("id", "annotation"):
            summary["text_graphs"] += 1
            refs = reverse.get(graph.id)
            if not refs:
                summary["unreferenced"] += 1
                continue
            summary["linked"] += 1
            if apply_changes:
                annotation = graph.annotation or {}
                props = annotation.setdefault("properties", {})
                # Record the original elementid (None when there was none) so
                # --reverse can faithfully restore *or remove* the synthetic value.
                if "legacy_dpt_elementid" not in props:
                    props["legacy_dpt_elementid"] = props.get("elementid")
                props["elementid"] = {"refs": refs}
                with transaction.atomic():
                    graph.annotation = annotation
                    graph.save(update_fields=["annotation"])
                summary["written"] += 1

        self._print(summary)

    def _reverse(self) -> None:
        summary = {"text_graphs": 0, "restored": 0}
        self.stdout.write("Running REVERSE (restoring legacy_dpt_elementid → elementid).")
        for graph in Graph.objects.filter(annotation_type="text").only("id", "annotation"):
            summary["text_graphs"] += 1
            props = (graph.annotation or {}).get("properties") or {}
            if "legacy_dpt_elementid" not in props:
                continue
            legacy = props.pop("legacy_dpt_elementid")
            if legacy is None:
                props.pop("elementid", None)  # there was no original → remove synthetic
            else:
                props["elementid"] = legacy
            with transaction.atomic():
                graph.save(update_fields=["annotation"])
            summary["restored"] += 1
        self._print(summary)

    def _print(self, summary: dict[str, int]) -> None:
        self.stdout.write("--- elementid re-encode summary ---")
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
