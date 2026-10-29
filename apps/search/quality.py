"""Data-quality probes for the backoffice dashboard.

Each function returns a small dict that the dashboard renders as a card;
`quality_cards()` is what `views_management.quality_dashboard` serves. It
lives in `search` rather than `manuscripts` because the cards span
manuscripts, annotations and scribes, and `search` is the one app the
dependency graph lets import all three.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.scribes.models import Hand
from apps.search.documents.dpt_parser import extract_clauses


def _stale_drafts(days: int = 30) -> dict:
    cutoff = timezone.now() - timedelta(days=days)
    qs = ImageText.objects.filter(status=ImageText.Status.DRAFT, modified__lt=cutoff)
    return {
        "id": "stale-drafts",
        "label": f"Image-texts stuck in Draft >{days}d",
        "count": qs.count(),
        "sample": [
            {"id": r.id, "item_image": r.item_image_id, "modified": r.modified.isoformat()}
            for r in qs.order_by("modified")[:10]
        ],
    }


def _untyped_clauses() -> dict:
    """Image-texts whose data-dpt clauses have no `data-dpt-type` attribute.

    We don't pre-compute this; instead we sample the most recent 200 image-texts
    and run the parser server-side. Gives a "good enough" snapshot for the
    dashboard without scanning the entire corpus.
    """
    flagged: list[dict] = []
    for it in ImageText.objects.exclude(content="").order_by("-modified")[:200]:
        clauses = extract_clauses(it.content)
        without_type = [c for c in clauses if not c.get("type")]
        if without_type:
            flagged.append({"id": it.id, "count": len(without_type)})
    return {
        "id": "untyped-clauses",
        "label": "Recent image-texts with untyped clauses",
        "count": len(flagged),
        "sample": flagged[:10],
    }


def _undescribed_graphs() -> dict:
    qs = Graph.objects.annotate(component_count=Count("graphcomponent")).filter(component_count=0).order_by("-id")
    return {
        "id": "undescribed-graphs",
        "label": "Graphs with no components",
        "count": qs.count(),
        "sample": [{"id": g.id, "item_image": g.item_image_id} for g in qs[:10]],
    }


def _hands_without_images() -> dict:
    qs = Hand.objects.annotate(image_count=Count("item_part_images")).filter(image_count=0)
    return {
        "id": "hands-without-images",
        "label": "Hands with no attributed images",
        "count": qs.count(),
        "sample": [{"id": h.id, "name": h.name} for h in qs[:10]],
    }


def _orphan_text_graphs() -> dict:
    """TEXT-typed Graphs sitting on images whose ImageTexts are all empty.

    A TEXT graph is a region referenced from an ImageText.content span via
    `data-graph-id`. If every text on its image is blank, nothing can refer
    to it — that's a likely orphan.
    """
    qs = Graph.objects.filter(annotation_type=Graph.AnnotationType.TEXT).exclude(
        item_image__texts__content__regex=r".+"
    )
    return {
        "id": "orphan-text-graphs",
        "label": "TEXT-typed graphs on images with no text content",
        "count": qs.count(),
        "sample": [{"id": r.id, "item_image": r.item_image_id} for r in qs[:10]],
    }


def quality_cards() -> list[dict]:
    return [_stale_drafts(), _untyped_clauses(), _undescribed_graphs(), _hands_without_images(), _orphan_text_graphs()]
