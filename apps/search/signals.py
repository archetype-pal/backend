"""Index propagation for msDesc areas (TEI-descriptions roadmap 7.1).

The platform has no automatic index sync — reindexing is admin/CLI-only, and
the admin "in sync" check is count-based, so a `MsDescArea` content edit would
be invisible to it. These receivers make item-parts reindexing an INVARIANT of
MsDescArea mutation: any create/update/delete enqueues a full item-parts
rebuild once the surrounding transaction commits. Cheap at corpus size (~713
docs, atomic staging-index swap); the existing `reindex_lock` serialises
concurrent runs — a colliding run no-ops and self-heals on the next save.

The receivers live in `apps.search` (not `apps.manuscripts`) because the
architecture boundary allows search → manuscripts but not the reverse; wiring
happens in `SearchConfig.ready()`, mirroring how the audit handlers are
attached in `apps.manuscripts.apps`.
"""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.manuscripts.models import MsDescArea
from apps.search.tasks import reindex_search_index
from apps.search.types import IndexType


def _enqueue_item_parts_reindex() -> None:
    reindex_search_index.delay(IndexType.ITEM_PARTS.to_url_segment())


@receiver(post_save, sender=MsDescArea, dispatch_uid="msdescarea_reindex_item_parts:save")
def reindex_item_parts_on_msdesc_area_save(sender, instance: MsDescArea, **kwargs) -> None:
    transaction.on_commit(_enqueue_item_parts_reindex)


@receiver(post_delete, sender=MsDescArea, dispatch_uid="msdescarea_reindex_item_parts:delete")
def reindex_item_parts_on_msdesc_area_delete(sender, instance: MsDescArea, **kwargs) -> None:
    transaction.on_commit(_enqueue_item_parts_reindex)
