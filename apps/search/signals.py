"""Search index mutation signals and reindex propagation.

Receivers in this module wire mutation-level incremental sync for models
(e.g. Graph, GraphComponent, MsDescArea), distinct from the declarative
IndexRegistration registry in `registry.py` which defines document builders
and relationships for full corpus reindexing.

These receivers live in `apps.search` (not `apps.manuscripts`) because the
architecture boundary allows search → manuscripts but not the reverse; wiring
happens in `SearchConfig.ready()`, mirroring how the audit handlers are
attached in `apps.manuscripts.apps`.
"""

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.annotations.models import Graph, GraphComponent
from apps.manuscripts.models import MsDescArea
from apps.search.tasks import delete_search_documents, reindex_search_index, sync_search_documents
from apps.search.types import IndexType


def _auto_sync_enabled() -> bool:
    return bool(getattr(settings, "SEARCH_AUTO_REINDEX", True))


def _enqueue_item_parts_reindex() -> None:
    if not _auto_sync_enabled():
        return
    reindex_search_index.delay(IndexType.ITEM_PARTS.to_url_segment())


def _enqueue_graph_sync(graph_id: int, item_image_id: int | None = None) -> None:
    if not _auto_sync_enabled():
        return
    sync_search_documents.delay(IndexType.GRAPHS.to_url_segment(), [graph_id])
    if item_image_id:
        sync_search_documents.delay(IndexType.ITEM_IMAGES.to_url_segment(), [item_image_id])


def _enqueue_graph_delete(graph_id: int, item_image_id: int | None = None) -> None:
    if not _auto_sync_enabled():
        return
    delete_search_documents.delay(IndexType.GRAPHS.to_url_segment(), [graph_id])
    if item_image_id:
        sync_search_documents.delay(IndexType.ITEM_IMAGES.to_url_segment(), [item_image_id])


@receiver(post_save, sender=MsDescArea, dispatch_uid="msdescarea_reindex_item_parts:save")
def reindex_item_parts_on_msdesc_area_save(sender, instance: MsDescArea, **kwargs) -> None:
    transaction.on_commit(_enqueue_item_parts_reindex)


@receiver(post_delete, sender=MsDescArea, dispatch_uid="msdescarea_reindex_item_parts:delete")
def reindex_item_parts_on_msdesc_area_delete(sender, instance: MsDescArea, **kwargs) -> None:
    transaction.on_commit(_enqueue_item_parts_reindex)


@receiver(post_save, sender=Graph, dispatch_uid="graph_incremental_sync:save")
def sync_graph_on_save(sender, instance: Graph, **kwargs) -> None:
    pk = instance.pk
    item_image_id = getattr(instance, "item_image_id", None)
    if getattr(instance, "deleted_at", None) is not None:
        transaction.on_commit(lambda: _enqueue_graph_delete(pk, item_image_id))
    else:
        transaction.on_commit(lambda: _enqueue_graph_sync(pk, item_image_id))


@receiver(post_delete, sender=Graph, dispatch_uid="graph_incremental_sync:delete")
def sync_graph_on_delete(sender, instance: Graph, **kwargs) -> None:
    pk = instance.pk
    item_image_id = getattr(instance, "item_image_id", None)
    transaction.on_commit(lambda: _enqueue_graph_delete(pk, item_image_id))


@receiver(post_save, sender=GraphComponent, dispatch_uid="graph_component_incremental_sync:save")
def sync_graph_on_component_save(sender, instance: GraphComponent, **kwargs) -> None:
    graph_id = instance.graph_id
    if graph_id:
        item_image_id = getattr(instance.graph, "item_image_id", None)
        transaction.on_commit(lambda: _enqueue_graph_sync(graph_id, item_image_id))


@receiver(post_delete, sender=GraphComponent, dispatch_uid="graph_component_incremental_sync:delete")
def sync_graph_on_component_delete(sender, instance: GraphComponent, **kwargs) -> None:
    graph_id = instance.graph_id
    if graph_id:
        item_image_id = getattr(instance.graph, "item_image_id", None)
        transaction.on_commit(lambda: _enqueue_graph_sync(graph_id, item_image_id))
