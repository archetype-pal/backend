"""Image-text monitoring for the backoffice.

Aggregates the state of every transcription/translation row in the corpus into
a single dashboard payload: per-status × per-kind matrix, coverage across the
images that have at least one text, language distribution, and a feed of the
most-recently edited rows so the editorial team can see who is working on what.

Read-only, superuser-gated, served at
``/api/v1/search/management/image-texts/overview/``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.annotations.models import Graph
from apps.common.permissions import IsSuperuser
from apps.manuscripts.models import ImageText, ItemImage

KIND_VALUES: tuple[str, ...] = (
    ImageText.Type.TRANSCRIPTION,
    ImageText.Type.TRANSLATION,
)
STATUS_VALUES: tuple[str, ...] = (
    ImageText.Status.DRAFT,
    ImageText.Status.REVIEW,
    ImageText.Status.LIVE,
    ImageText.Status.REVIEWED,
)


def _status_matrix() -> dict[str, Any]:
    """status × kind matrix of counts plus a row-empty bucket per kind."""

    rows = ImageText.objects.values("type", "status").annotate(n=Count("id"))
    by_kind: dict[str, dict[str, int]] = {kind: dict.fromkeys(STATUS_VALUES, 0) for kind in KIND_VALUES}
    for row in rows:
        kind = row["type"]
        status = row["status"]
        if kind in by_kind and status in by_kind[kind]:
            by_kind[kind][status] = row["n"]

    empty_by_kind: dict[str, int] = {}
    for kind in KIND_VALUES:
        empty_by_kind[kind] = ImageText.objects.filter(type=kind, content="").count()

    totals = {kind: sum(by_kind[kind].values()) for kind in KIND_VALUES}
    return {
        "kinds": list(KIND_VALUES),
        "statuses": list(STATUS_VALUES),
        "by_kind": by_kind,
        "empty_by_kind": empty_by_kind,
        "totals": totals,
    }


def _coverage() -> dict[str, Any]:
    """Per-image coverage. How many images have transcription / translation / both."""

    has_transcription = ImageText.objects.filter(item_image_id=OuterRef("pk"), type=ImageText.Type.TRANSCRIPTION)
    has_translation = ImageText.objects.filter(item_image_id=OuterRef("pk"), type=ImageText.Type.TRANSLATION)
    qs = ItemImage.objects.annotate(
        has_transcr=Exists(has_transcription),
        has_transl=Exists(has_translation),
    )
    images_total = qs.count()
    with_transcr = qs.filter(has_transcr=True).count()
    with_transl = qs.filter(has_transl=True).count()
    with_both = qs.filter(has_transcr=True, has_transl=True).count()
    with_either = qs.filter(Q(has_transcr=True) | Q(has_transl=True)).count()
    return {
        "images_total": images_total,
        "with_transcription": with_transcr,
        "with_translation": with_transl,
        "with_both": with_both,
        "with_either": with_either,
        "with_neither": images_total - with_either,
    }


def _languages(limit: int = 12) -> list[dict[str, Any]]:
    """Top languages, with per-kind breakdown."""

    rows = ImageText.objects.exclude(language="").values("language", "type").annotate(n=Count("id"))
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(KIND_VALUES, 0))
    for row in rows:
        grouped[row["language"]][row["type"]] = row["n"]
    out = [
        {
            "language": lang,
            "transcription": counts.get(ImageText.Type.TRANSCRIPTION, 0),
            "translation": counts.get(ImageText.Type.TRANSLATION, 0),
            "total": sum(counts.values()),
        }
        for lang, counts in grouped.items()
    ]
    out.sort(key=lambda r: r["total"], reverse=True)
    blank_count = ImageText.objects.filter(language="").count()
    return (
        [
            *out[:limit],
            {
                "language": "(unset)",
                "transcription": ImageText.objects.filter(language="", type=ImageText.Type.TRANSCRIPTION).count(),
                "translation": ImageText.objects.filter(language="", type=ImageText.Type.TRANSLATION).count(),
                "total": blank_count,
            },
        ]
        if blank_count
        else out[:limit]
    )


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
                filter=Q(item_image__graphs__annotation_type="text"),
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


@api_view(["GET"])
@permission_classes([IsSuperuser])
def text_monitoring_overview(request):
    return Response(
        {
            "generated_at": timezone.now().isoformat(),
            "matrix": _status_matrix(),
            "coverage": _coverage(),
            "languages": _languages(),
            "recent": _recent_activity(),
            "activity": _activity_buckets(),
            "annotation_health": _annotation_health(),
        }
    )
