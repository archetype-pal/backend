"""Mutation-level incremental sync, as opposed to the full reindex `registry.py`
declares.

The receivers live here rather than in `apps.manuscripts` because the
architecture boundary allows search → manuscripts but not the reverse; they are
wired in `SearchConfig.ready()`.

Most models are driven by the declarative map in `dependencies.py`. Graph and
GraphComponent keep hand-written receivers because one graph write fans out into
many component writes in the same request and needs coalescing.
"""

from collections.abc import Iterable
from functools import partial
from itertools import islice
import threading

from django.conf import settings
from django.core.signals import request_finished
from django.db import models, transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from apps.annotations.models import Graph, GraphComponent
from apps.manuscripts.models import ImageText
from apps.search.dependencies import DEPENDENCIES, TEXT_INDEXES
from apps.search.tasks import delete_search_documents, sync_search_documents
from apps.search.types import IndexType

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

    transaction.on_commit(_run)


def _auto_sync_enabled() -> bool:
    return bool(getattr(settings, "SEARCH_AUTO_REINDEX", True))


def _enqueue(index_type: IndexType, pks: Iterable[int]) -> None:
    """Queue a sync for these source rows, in chunks.

    Runs after the transaction committed. A queryset is streamed with
    `.iterator()`, since plain `iter()` fills its result cache first. A delete
    hands over a list, because by now its rows are gone.
    """
    if not _auto_sync_enabled():
        return
    segment = index_type.to_url_segment()
    remaining = pks.iterator(chunk_size=SYNC_CHUNK_SIZE) if isinstance(pks, QuerySet) else iter(pks)
    while chunk := list(islice(remaining, SYNC_CHUNK_SIZE)):
        sync_search_documents.delay(segment, chunk)


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
            transaction.on_commit(partial(_enqueue, index_type, pks))


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


@receiver(post_save, sender=Graph, dispatch_uid="graph_incremental_sync:save")
def sync_graph_on_save(sender, instance: Graph, **kwargs) -> None:
    if kwargs.get("raw"):
        return
    pk = instance.pk
    item_image_id = getattr(instance, "item_image_id", None)
    if instance.annotation_type == Graph.AnnotationType.TEXT:
        transaction.on_commit(lambda: _enqueue_text_sync_for_image(item_image_id))
    if getattr(instance, "deleted_at", None) is not None:
        transaction.on_commit(lambda: _enqueue_graph_delete(pk, item_image_id))
    else:
        _schedule_graph_sync(pk, item_image_id)


@receiver(post_delete, sender=Graph, dispatch_uid="graph_incremental_sync:delete")
def sync_graph_on_delete(sender, instance: Graph, **kwargs) -> None:
    pk = instance.pk
    item_image_id = getattr(instance, "item_image_id", None)
    if instance.annotation_type == Graph.AnnotationType.TEXT:
        transaction.on_commit(lambda: _enqueue_text_sync_for_image(item_image_id))
    transaction.on_commit(lambda: _enqueue_graph_delete(pk, item_image_id))


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
