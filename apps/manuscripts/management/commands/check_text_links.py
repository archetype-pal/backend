"""Integrity check for text↔region links (text_annotation plan, Phase 1).

Walks every ImageText, parses its in-text graph references, and flags any that
point at a missing Graph, a non-TEXT Graph, or a Graph on a different image
than the text. Read-only; exits non-zero when problems are found so it can gate
CI or a pre-migration check.

A ref to a trashed region is counted, not a problem: the trash keeps the ref on
purpose so a restore needs no replay.
"""

from django.core.management.base import BaseCommand

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import parse_graph_refs


class Command(BaseCommand):
    help = "Report text↔region links that point at missing, non-TEXT, or cross-image Graphs."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--verbose-ok", action="store_true", help="Also print healthy totals per row.")

    def handle(self, *args, **options) -> None:
        # all_objects: a trashed region keeps its refs by design, so resolving
        # through the live-only default manager would report it as missing.
        graphs = {
            gid: (annotation_type, image_id, deleted_at)
            for gid, annotation_type, image_id, deleted_at in Graph.all_objects.values_list(
                "id", "annotation_type", "item_image_id", "deleted_at"
            )
        }

        summary = {"texts": 0, "links": 0, "missing": 0, "non_text": 0, "cross_image": 0, "trashed": 0}
        problems: list[str] = []

        for it in ImageText.objects.all().only("id", "content", "item_image_id"):
            summary["texts"] += 1
            for ref in parse_graph_refs(it.content or ""):
                for gid in ref.graph_ids:
                    summary["links"] += 1
                    graph = graphs.get(gid)
                    if graph is None:
                        summary["missing"] += 1
                        problems.append(f"ImageText #{it.id}: ref → Graph {gid} does not exist")
                        continue
                    annotation_type, image_id, deleted_at = graph
                    if annotation_type != "text":
                        summary["non_text"] += 1
                        problems.append(f"ImageText #{it.id}: ref → Graph {gid} is '{annotation_type}', not text")
                    elif image_id != it.item_image_id:
                        summary["cross_image"] += 1
                        problems.append(
                            f"ImageText #{it.id} (image {it.item_image_id}): ref → Graph {gid} on image {image_id}"
                        )
                    elif deleted_at is not None:
                        summary["trashed"] += 1

        self.stdout.write("--- text-link integrity ---")
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
        if problems:
            self.stdout.write("")
            for line in problems[:100]:
                self.stdout.write(line)
            if len(problems) > 100:
                self.stdout.write(f"... and {len(problems) - 100} more")
            self.stderr.write(f"FAILED: {len(problems)} problem link(s) found.")
            raise SystemExit(1)
        if summary["trashed"]:
            self.stdout.write(
                f"All text↔region links resolve to valid Graphs "
                f"({summary['links'] - summary['trashed']} live, {summary['trashed']} pending in trash)."
            )
        else:
            self.stdout.write("All text↔region links resolve to live TEXT Graphs on the same image.")
