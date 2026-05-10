"""Data-quality probes for the backoffice dashboard (M8.4).

Each function returns a small dict that the dashboard renders as a card.
The endpoint at /api/v1/manuscripts/management/quality/ aggregates them.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.annotations.models import Graph
from apps.common.permissions import IsSuperuser
from apps.manuscripts.models import ImageText


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
    from apps.search.documents.dpt_parser import extract_clauses

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
    from apps.scribes.models import Hand

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


@api_view(["GET"])
@permission_classes([IsSuperuser])
def quality_dashboard(request):
    return Response(
        {
            "generated_at": timezone.now().isoformat(),
            "cards": [
                _stale_drafts(),
                _untyped_clauses(),
                _undescribed_graphs(),
                _hands_without_images(),
                _orphan_text_graphs(),
            ],
        }
    )
