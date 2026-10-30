"""Mutation-level incremental sync, as opposed to the full reindex `registry.py`
declares.

The receivers live here rather than in `apps.manuscripts` because the
architecture boundary allows search → manuscripts but not the reverse; they are
wired in `SearchConfig.ready()`.

Most models are driven by the declarative map in `dependencies.py`. Graph and
GraphComponent keep hand-written receivers because one graph write fans out into
many component writes in the same request and needs coalescing. ItemImage has
two more, for the item part an image is moved away from.
"""

from collections.abc import Iterable
from functools import partial
from itertools import islice
import logging
import threading

from django.conf import settings
from django.core.signals import request_finished
from django.db import models, transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from apps.annotations.models import Graph, GraphComponent
from apps.manuscripts.models import ImageText, ItemImage
from apps.search.dependencies import DEPENDENCIES, TEXT_INDEXES
from apps.search.tasks import delete_search_documents, sync_search_documents
from apps.search.types import IndexType

logger = logging.getLogger(__name__)

# Matches `IndexingService.REINDEX_BATCH_SIZE`. One edit can invalidate a large
# share of an index, and a task per document would flood the queue.
SYNC_CHUNK_SIZE = 500

# One Graph save fans out into several component writes in the same request,
# each signalling a sync for the same graph_id; this coalesces them into a
# single enqueue per transaction. `request_finished` clears the set as well,
# because on_commit never runs for a rolled-back transaction and a stuck id
# would suppress a later request's sync on a reused worker thread.
_pending_graph_syncs = threading.local()


@receiver(request_finished, dispatch_uid="graph_incremental_sync:clear_pending")
def _clear_pending_graph_syncs(sender, **kwargs) -> None:
    _pending_graph_syncs.ids = None


def _graph_sync_pending(graph_id: int) -> bool:
    pending = getattr(_pending_graph_syncs, "ids", None)
    return pending is not None and graph_id in pending


def _schedule_graph_sync(graph_id: int, item_image_id: int | None) -> None:
    pending = getattr(_pending_graph_syncs, "ids", None)
    if pending is None:
        pending = set()
        _pending_graph_syncs.ids = pending
    if graph_id in pending:
        return
    pending.add(graph_id)

    def _run() -> None:
        pending.discard(graph_id)
        _enqueue_graph_sync(graph_id, item_image_id)

    transaction.on_commit(_run, robust=True)


def _auto_sync_enabled() -> bool:
    return bool(settings.SEARCH_AUTO_REINDEX)


def _queue(task, index_type: IndexType, pks: list[int]) -> None:
    """Send one sync task; a broker outage is logged, never raised.

    These run from `on_commit`, i.e. inside the write that triggered them. A
    search outage must not turn that write into a 500 — the row is already
    committed, and the runbook's answer to a lost sync is a reindex.
    """
    try:
        task.delay(index_type.segment, pks)
    except Exception:
        logger.exception(
            "Could not queue %s for %s (%d rows); reindex it to recover.", task.name, index_type.segment, len(pks)
        )


def _enqueue(index_type: IndexType, pks: Iterable[int]) -> None:
    """Queue a sync for these source rows, in chunks.

    Runs after the transaction committed. A queryset is streamed with
    `.iterator()`, since plain `iter()` fills its result cache first. A delete
    hands over a list, because by now its rows are gone.
    """
    if not _auto_sync_enabled():
        return
    remaining = pks.iterator(chunk_size=SYNC_CHUNK_SIZE) if isinstance(pks, QuerySet) else iter(pks)
    while chunk := list(islice(remaining, SYNC_CHUNK_SIZE)):
        _queue(sync_search_documents, index_type, chunk)


def _enqueue_text_sync_for_image(item_image_id: int | None) -> None:
    """Rebuild the text-derived documents on an image.

    They bake a TEXT graph's polygon in to crop a thumbnail from, so redrawing a
    region has to rebuild them too.
    """
    if not item_image_id:
        return
    texts = ImageText.objects.filter(item_image_id=item_image_id).values_list("id", flat=True)
    for index_type in TEXT_INDEXES:
        _enqueue(index_type, texts)


def _enqueue_graph_change(graph_task, graph_id: int, item_image_id: int | None = None) -> None:
    """Queue `graph_task` for the graph and, as its image document counts graphs, a sync of the image."""
    if not _auto_sync_enabled():
        return
    _queue(graph_task, IndexType.GRAPHS, [graph_id])
    if item_image_id:
        _queue(sync_search_documents, IndexType.ITEM_IMAGES, [item_image_id])


def _enqueue_graph_sync(graph_id: int, item_image_id: int | None = None) -> None:
    _enqueue_graph_change(sync_search_documents, graph_id, item_image_id)


def _enqueue_graph_delete(graph_id: int, item_image_id: int | None = None) -> None:
    _enqueue_graph_change(delete_search_documents, graph_id, item_image_id)


def sync_dependent_documents(instance: models.Model, *, resolve_now: bool = False) -> None:
    """Queue every index this write invalidates, per `dependencies.DEPENDENCIES`.

    Resolvers run here so their filters capture the row's ids while they are
    still set, and the querysets they return stay unevaluated until `on_commit`.

    A delete evaluates them now instead, and does it from `pre_delete`: Django's
    collector runs its SET_NULL updates between the two delete signals, so by
    `post_delete` the dependents are detached and a resolver finds nothing.
    """
    for dependency in DEPENDENCIES[type(instance)]:
        pks = dependency.resolve(instance)
        if resolve_now:
            pks = list(pks)
        for index_type in dependency.indexes:
            transaction.on_commit(partial(_enqueue, index_type, pks), robust=True)


def _register_dependency_receivers(model: type[models.Model]) -> None:
    label = model._meta.label_lower

    def on_save(sender, instance: models.Model, **kwargs) -> None:
        if kwargs.get("raw"):
            return  # loaddata: related rows may not exist yet, and a restore reindexes anyway
        sync_dependent_documents(instance)

    def on_delete(sender, instance: models.Model, **kwargs) -> None:
        sync_dependent_documents(instance, resolve_now=True)

    # weak=False: these closures have no other reference and would otherwise be
    # garbage collected straight after connecting. Listening to a delete signal
    # at all is also what stops Django fast-deleting these rows, which is what
    # makes them fire for cascaded objects.
    post_save.connect(on_save, sender=model, dispatch_uid=f"incremental_sync:{label}:save", weak=False)
    pre_delete.connect(on_delete, sender=model, dispatch_uid=f"incremental_sync:{label}:delete", weak=False)


for _model in DEPENDENCIES:
    _register_dependency_receivers(_model)


@receiver(pre_save, sender=ItemImage, dispatch_uid="item_image_incremental_sync:part_left")
def remember_item_part_an_image_leaves(sender, instance: ItemImage, **kwargs) -> None:
    # The dependency map runs after the save, when only the new part is known.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"item_part", "item_part_id"} & update_fields:
        return
    if kwargs.get("raw") or instance.pk is None or not _auto_sync_enabled():
        return
    old_part_id = ItemImage.objects.filter(pk=instance.pk).values_list("item_part_id", flat=True).first()
    if old_part_id is not None and old_part_id != instance.item_part_id:
        instance._item_part_left = old_part_id


@receiver(post_save, sender=ItemImage, dispatch_uid="item_image_incremental_sync:part_left_sync")
def sync_item_part_an_image_left(sender, instance: ItemImage, **kwargs) -> None:
    # Queued only now: outside a transaction on_commit runs at once, and from
    # pre_save that would rebuild the old part before the row is written.
    old_part_id = instance.__dict__.pop("_item_part_left", None)
    if old_part_id is not None:
        transaction.on_commit(partial(_enqueue, IndexType.ITEM_PARTS, [old_part_id]), robust=True)


# The text-derived documents bake in the polygon of a linked TEXT region but
# leave out editorial ones (public indexes), so a change of type to or from
# either has to rebuild them.
_TEXT_DOCUMENT_GRAPH_TYPES = {Graph.AnnotationType.TEXT, Graph.AnnotationType.EDITORIAL}


@receiver(pre_save, sender=Graph, dispatch_uid="graph_incremental_sync:type_change")
def remember_a_graph_type_change_the_text_documents_see(sender, instance: Graph, **kwargs) -> None:
    # The post_save receiver runs after the save, when only the new type is known.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "annotation_type" not in update_fields:
        return
    if kwargs.get("raw") or instance.pk is None or not _auto_sync_enabled():
        return
    old_type = Graph.all_objects.filter(pk=instance.pk).values_list("annotation_type", flat=True).first()
    if old_type != instance.annotation_type and {old_type, instance.annotation_type} & _TEXT_DOCUMENT_GRAPH_TYPES:
        instance._text_document_type_changed = True


@receiver(post_save, sender=Graph, dispatch_uid="graph_incremental_sync:save")
def sync_graph_on_save(sender, instance: Graph, **kwargs) -> None:
    type_changed = instance.__dict__.pop("_text_document_type_changed", False)
    if kwargs.get("raw"):
        return
    pk = instance.pk
    item_image_id = getattr(instance, "item_image_id", None)
    if instance.annotation_type == Graph.AnnotationType.TEXT or type_changed:
        transaction.on_commit(lambda: _enqueue_text_sync_for_image(item_image_id), robust=True)
    if getattr(instance, "deleted_at", None) is not None:
        transaction.on_commit(lambda: _enqueue_graph_delete(pk, item_image_id), robust=True)
    else:
        _schedule_graph_sync(pk, item_image_id)


@receiver(post_delete, sender=Graph, dispatch_uid="graph_incremental_sync:delete")
def sync_graph_on_delete(sender, instance: Graph, **kwargs) -> None:
    pk = instance.pk
    item_image_id = getattr(instance, "item_image_id", None)
    if instance.annotation_type == Graph.AnnotationType.TEXT:
        transaction.on_commit(lambda: _enqueue_text_sync_for_image(item_image_id), robust=True)
    transaction.on_commit(lambda: _enqueue_graph_delete(pk, item_image_id), robust=True)


@receiver(post_save, sender=GraphComponent, dispatch_uid="graph_component_incremental_sync:save")
def sync_graph_on_component_save(sender, instance: GraphComponent, **kwargs) -> None:
    if kwargs.get("raw"):
        return
    graph_id = instance.graph_id
    if graph_id and not _graph_sync_pending(graph_id):
        item_image_id = getattr(instance.graph, "item_image_id", None)
        _schedule_graph_sync(graph_id, item_image_id)


@receiver(post_delete, sender=GraphComponent, dispatch_uid="graph_component_incremental_sync:delete")
def sync_graph_on_component_delete(sender, instance: GraphComponent, **kwargs) -> None:
    graph_id = instance.graph_id
    if graph_id and not _graph_sync_pending(graph_id):
        item_image_id = getattr(instance.graph, "item_image_id", None)
        _schedule_graph_sync(graph_id, item_image_id)
