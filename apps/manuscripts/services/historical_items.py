"""Query shaping for the historical-item management endpoints."""

from django.db.models import Count, OuterRef, Prefetch, QuerySet, Subquery

from apps.manuscripts.models import HistoricalItem, ItemImage, ItemPart


def optimize_historical_item_management_queryset(
    queryset: QuerySet[HistoricalItem], *, action: str | None
) -> QuerySet[HistoricalItem]:
    if action == "list":
        # Sort keys for the first part's current item, the one the list shows.
        first_part = ItemPart.objects.filter(historical_item=OuterRef("pk"), current_item__isnull=False).order_by("pk")
        return (
            queryset.select_related("date", "format")
            .prefetch_related("catalogue_numbers__catalogue")
            .annotate(
                part_count=Count("itempart", distinct=True),
                image_count=Count("itempart__images", distinct=True),
                first_repository_label=Subquery(first_part.values("current_item__repository__label")[:1]),
                first_shelfmark=Subquery(first_part.values("current_item__shelfmark")[:1]),
            )
        )
    if action == "retrieve":
        # The workspace payload nests every part with its images (plus text
        # counts and tags) and msDesc areas; see ItemPartWorkspaceSerializer.
        parts = ItemPart.objects.select_related("current_item__repository").prefetch_related(
            Prefetch("images", queryset=ItemImage.objects.annotate(text_count=Count("texts")).prefetch_related("tags")),
            "msdesc_areas",
        )
        return queryset.select_related("date", "format").prefetch_related(
            "catalogue_numbers__catalogue",
            "descriptions__source",
            "date_assessments",
            Prefetch("itempart_set", queryset=parts),
        )
    return queryset
