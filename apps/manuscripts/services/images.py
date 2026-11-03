"""Rules about an ItemImage: moving it between parts, counting its annotations, naming its tags."""

from collections.abc import Iterable

from django.db.models import Count, Q, QuerySet

from apps.annotations.models import Graph
from apps.manuscripts.models import ItemImage


def hand_attribution_error(image: ItemImage) -> str | None:
    """Why `image` cannot move to another item part, or None if it can.

    A hand belongs to one item part, so a moved image would keep pointing at
    hands of the part it left.
    """
    problems = []
    annotated = Graph.all_objects.filter(item_image=image, hand__isnull=False)
    if count := annotated.count():
        trashed = annotated.filter(deleted_at__isnull=False).count()
        problems.append(f"Annotations with a hand: {count}" + (f" ({trashed} in the trash)." if trashed else "."))
    if hand_names := list(image.hands.values_list("name", flat=True)):
        problems.append(f"Linked hands: {', '.join(hand_names)}.")
    if problems:
        return " ".join(["An image with hand attributions cannot be moved to another item part.", *problems])
    return None


def with_annotation_count(queryset: QuerySet[ItemImage]) -> QuerySet[ItemImage]:
    """Annotate ``annotation_count`` with the live graphs only. Reverse aggregates bypass the
    live-objects manager, so the ``deleted_at`` filter is spelled out here."""
    return queryset.annotate(annotation_count=Count("graphs", filter=Q(graphs__deleted_at__isnull=True), distinct=True))


def normalized_tag_names(names: Iterable[str]) -> list[str]:
    """Tag names as every writer of `ItemImage.tags` stores them: trimmed, lower-cased, blanks and repeats dropped.

    The repeats matter: Tagulous's manager skips only tags already on the image,
    so "Damaged, damaged" would otherwise count one relation twice in the tag's
    usage count. Lower-casing is explicit because the field's `force_lowercase`
    applies only when a string is assigned, and assigning a string also splits a
    comma-free value on spaces.
    """
    return list(dict.fromkeys(name for name in (raw.strip().lower() for raw in names) if name))
