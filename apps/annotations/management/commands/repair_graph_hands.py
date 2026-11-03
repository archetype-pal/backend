"""Report, and on `--apply` repair, graphs whose hand belongs to another part.

See `apps.annotations.services.hand_repair` for the rule. Without `--apply` this writes nothing.
"""

from itertools import groupby

from django.core.management.base import BaseCommand

from apps.annotations.services.hand_repair import (
    apply_graph_hand_repairs,
    cross_part_attributions,
    graph_hand_breaches,
)


def _ids(ids: list[int]) -> str:
    return ", ".join(map(str, ids)) if len(ids) <= 12 else f"{', '.join(map(str, ids[:12]))}, … ({len(ids)})"


class Command(BaseCommand):
    help = "Move graphs off another part's hand onto their own part's matching hand. Dry run unless --apply."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--apply", action="store_true", help="Move the repairable graphs (default: dry run).")

    def handle(self, *args, **options) -> None:
        breaches = graph_hand_breaches()
        repairable = [b for b in breaches if b.to_hand_id is not None]
        review = [b for b in breaches if b.to_hand_id is None]
        ticks = cross_part_attributions()

        def group_key(b):
            return (b.image_part_id, b.hand_id, b.hand_name, b.hand_part_id, b.to_hand_id, b.to_hand_name)

        self.stdout.write(f"Graphs on another part's hand: {len(breaches)}")
        self.stdout.write(
            f"  repairable (one hand on the image's part has the same name and scribe): {len(repairable)}"
        )
        self.stdout.write(f"  left for review: {len(review)}")
        self.stdout.write(f"Attribution ticks across parts (never changed here): {len(ticks)}")

        self.stdout.write("\nRepairable, by the image's part:")
        for (part, hand, name, hand_part, to_hand, to_name), moving in groupby(repairable, key=group_key):
            ids = [b.graph_id for b in moving]
            self.stdout.write(
                f"  part {part}: hand #{hand} '{name}' (part {hand_part}) → hand #{to_hand} '{to_name}': "
                f"{len(ids)} graphs [{_ids(ids)}]"
            )

        self.stdout.write("\nFor review, by the image's part:")
        for (part, hand, name, hand_part, _, _), group in groupby(review, key=group_key):
            held = list(group)
            candidates = "; ".join(f"#{i} '{n}' by {s}" for i, n, s in held[0].candidates) or "none"
            kinds = sorted({b.annotation_type for b in held})
            self.stdout.write(
                f"  part {part}: hand #{hand} '{name}' (part {hand_part}), {len(held)} {'/'.join(kinds)} graphs "
                f"[{_ids([b.graph_id for b in held])}]; the part's hands: {candidates}"
            )

        if ticks:
            self.stdout.write("\nAttribution ticks across parts:")
            for tick in ticks:
                self.stdout.write(
                    f"  hand #{tick.hand_id} '{tick.hand_name}' (part {tick.hand_part_id}) is ticked on "
                    f"image {tick.image_id} (part {tick.image_part_id})"
                )

        if options["apply"]:
            moved = apply_graph_hand_repairs(repairable)
            self.stdout.write(self.style.SUCCESS(f"\nMoved {moved} graphs."))
        elif repairable:
            self.stdout.write(self.style.WARNING("\nDry run: nothing written. Re-run with --apply to move them."))
