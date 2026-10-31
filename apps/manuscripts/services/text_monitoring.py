"""Image-text monitoring for the backoffice dashboard.

Aggregates every transcription/translation row into one payload: status x kind
matrix, per-image coverage, language distribution and a feed of recent edits.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, cast

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText, ItemImage

KIND_VALUES: tuple[str, ...] = tuple(ImageText.Type.values)
STATUS_VALUES: tuple[str, ...] = tuple(ImageText.Status.values)


def _status_matrix() -> dict[str, Any]:
    """status × kind matrix of counts plus a row-empty bucket per kind."""
    by_kind: dict[str, dict[str, int]] = {kind: dict.fromkeys(STATUS_VALUES, 0) for kind in KIND_VALUES}
    empty_by_kind: dict[str, int] = dict.fromkeys(KIND_VALUES, 0)
    rows = ImageText.objects.values("type", "status").annotate(n=Count("id"), empty=Count("id", filter=Q(content="")))
    for row in rows:
        kind, status = row["type"], row["status"]
        if kind in by_kind and status in by_kind[kind]:
            by_kind[kind][status] = row["n"]
            empty_by_kind[kind] += row["empty"]
    return {
        "kinds": list(KIND_VALUES),
        "statuses": list(STATUS_VALUES),
        "by_kind": by_kind,
        "empty_by_kind": empty_by_kind,
        "totals": {kind: sum(by_kind[kind].values()) for kind in KIND_VALUES},
    }


def _coverage() -> dict[str, Any]:
    """Per-image coverage: how many images have a transcription / translation / both."""
    texts = ImageText.objects.filter(item_image_id=OuterRef("pk"))
    counts = ItemImage.objects.annotate(
        has_transcr=Exists(texts.filter(type=ImageText.Type.TRANSCRIPTION)),
        has_transl=Exists(texts.filter(type=ImageText.Type.TRANSLATION)),
    ).aggregate(
        images_total=Count("id"),
        with_transcription=Count("id", filter=Q(has_transcr=True)),
        with_translation=Count("id", filter=Q(has_transl=True)),
        with_both=Count("id", filter=Q(has_transcr=True, has_transl=True)),
        with_either=Count("id", filter=Q(has_transcr=True) | Q(has_transl=True)),
    )
    return {**counts, "with_neither": counts["images_total"] - counts["with_either"]}


def _languages(limit: int = 12) -> list[dict[str, Any]]:
    """Top languages with a per-kind breakdown; rows with no language are one trailing `(unset)` bucket."""
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(KIND_VALUES, 0))
    for row in ImageText.objects.values("language", "type").annotate(n=Count("id")):
        grouped[row["language"] or "(unset)"][row["type"]] = row["n"]
    unset = grouped.pop("(unset)", None)
    out = [
        {
            "language": lang,
            "transcription": counts[ImageText.Type.TRANSCRIPTION],
            "translation": counts[ImageText.Type.TRANSLATION],
            "total": sum(counts.values()),
        }
        for lang, counts in grouped.items()
    ]
    out.sort(key=lambda r: cast(int, r["total"]), reverse=True)
    out = out[:limit]
    if unset:
        out.append(
            {
                "language": "(unset)",
                "transcription": unset[ImageText.Type.TRANSCRIPTION],
                "translation": unset[ImageText.Type.TRANSLATION],
                "total": sum(unset.values()),
            }
        )
    return out


def _recent_activity(limit: int = 25) -> list[dict[str, Any]]:
    """The N most-recently modified image-texts, with annotation counts.

    `annotation_count` is the number of TEXT-typed Graphs on the same image —
    a stand-in for "regions linkable from this text," cheap to compute as a
    queryset annotation rather than parsing `data-graph-id` out of each
    row's HTML.
    """

    qs = (
        ImageText.objects.select_related("item_image", "item_image__item_part")
        .annotate(
            annotation_count=Count(
                "item_image__graphs",
                # A joined relation, so the live-only default manager does not apply.
                filter=Q(
                    item_image__graphs__annotation_type=Graph.AnnotationType.TEXT,
                    item_image__graphs__deleted_at__isnull=True,
                ),
            )
        )
        .order_by("-modified")[:limit]
    )
    out: list[dict[str, Any]] = []
    for it in qs:
        ip = it.item_image
        item_part = getattr(ip, "item_part", None)
        out.append(
            {
                "id": it.id,
                "type": it.type,
                "status": it.status,
                "language": it.language,
                "modified": it.modified.isoformat(),
                "created": it.created.isoformat(),
                "is_empty": not it.content,
                "char_count": len(it.content),
                "annotation_count": it.annotation_count,
                "item_image_id": ip.id,
                "item_part_id": item_part.id if item_part else None,
                "locus": ip.locus or "",
                "label": str(ip),
            }
        )
    return out


def _activity_buckets(days: int = 30) -> list[dict[str, Any]]:
    """Daily edit volume for the last ``days`` days, grouped by kind."""

    cutoff = timezone.now() - timedelta(days=days)
    qs = ImageText.objects.filter(modified__gte=cutoff).values("type", "modified")
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(KIND_VALUES, 0))
    for row in qs:
        day = row["modified"].date().isoformat()
        kind = row["type"]
        if kind in KIND_VALUES:
            buckets[day][kind] = buckets[day].get(kind, 0) + 1
    return [
        {
            "date": day,
            "transcription": counts.get(ImageText.Type.TRANSCRIPTION, 0),
            "translation": counts.get(ImageText.Type.TRANSLATION, 0),
        }
        for day, counts in sorted(buckets.items())
    ]


def _annotation_activity(days: int = 30) -> list[dict[str, Any]]:
    """Daily count of new text-annotation `Graph` rows over the last ``days``.

    Complements `_activity_buckets`: that one tracks edits to existing
    image-texts, this one tracks the regions linkable from texts being
    drawn fresh. A flat 30-day text-edit curve with a rising annotation
    curve means editors are anchoring older transcriptions to image
    regions rather than typing new text.
    """

    cutoff = timezone.now() - timedelta(days=days)
    qs = Graph.objects.filter(annotation_type=Graph.AnnotationType.TEXT, created__gte=cutoff).values("created")
    buckets: dict[str, int] = defaultdict(int)
    for row in qs:
        buckets[row["created"].date().isoformat()] += 1
    return [{"date": day, "count": count} for day, count in sorted(buckets.items())]


def _annotation_health() -> dict[str, Any]:
    """Quick read on how well-annotated the corpus' texts are.

    A text annotation is a TEXT-typed Graph row — a region on an image that
    `ImageText.content` references via a `data-graph-id` attribute on a span.
    """

    total = ImageText.objects.count()
    with_content = ImageText.objects.exclude(content="").count()
    annotations_total = Graph.objects.filter(annotation_type=Graph.AnnotationType.TEXT).count()
    return {
        "image_texts_total": total,
        "image_texts_with_content": with_content,
        "annotations_total": annotations_total,
        "average_annotations_per_text": (round(annotations_total / with_content, 2) if with_content else 0.0),
    }


def text_monitoring_overview() -> dict[str, Any]:
    return {
        "generated_at": timezone.now().isoformat(),
        "matrix": _status_matrix(),
        "coverage": _coverage(),
        "languages": _languages(),
        "recent": _recent_activity(),
        "activity": _activity_buckets(),
        "annotation_activity": _annotation_activity(),
        "annotation_health": _annotation_health(),
    }
