"""Signals that keep text↔region links consistent.

Really deleting a TEXT-region Graph must also strip its in-text reference
(`corresp="#gid-N"` / `data-graph-id`) from the transcription, or the markup is
left pointing at a graph that no longer exists. The dedicated unlink-region
endpoint does this explicitly, but a Graph can be hard-deleted by other paths
too (the management purge action, an ItemImage cascade). This signal makes
corresp-stripping an invariant of graph *deletion*.

It deliberately does not fire on a trash: `soft_delete()` is a save(), and
keeping the ref is what makes restore replay-free. A trashed region therefore
reads as `exists: true, trashed: true` from `image-texts/{id}/regions/` — see
`ImageTextViewSet.regions`.
"""

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.annotations.models import Graph

from .models import ImageText
from .services.tei import remove_graph_ref


@receiver(pre_delete, sender=Graph, dispatch_uid="strip_text_region_corresp")
def strip_text_region_corresp(sender, instance: Graph, **kwargs) -> None:
    """When a TEXT-region Graph is deleted, remove its reference from every text
    of the same image. No-op for image/editorial graphs and for texts that don't
    reference it (remove_graph_ref is idempotent)."""
    if instance.annotation_type != Graph.AnnotationType.TEXT:
        return

    for text in ImageText.objects.filter(item_image_id=instance.item_image_id):
        updated = remove_graph_ref(text.content or "", instance.id)
        if updated != (text.content or ""):
            text.content = updated
            text.save(update_fields=["content", "modified"])
