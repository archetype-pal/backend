import logging

from celery import shared_task
from django.apps import apps
from django.core.management import call_command
from django.db import reset_queries

from haystack import connections
from haystack.exceptions import NotHandled

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_RETRIES = 5


@shared_task
def async_update_index(model_names=None):
    logger.info("Starting asynchronous index update task.")
    call_command("update_index")
    logger.info("Asynchronous index update task completed.")


def _get_model_and_index(model_label, using="default"):
    """Resolve model label (e.g. 'manuscripts.ItemPart') to model and Haystack index."""
    app_label, model_name = model_label.rsplit(".", 1)
    model = apps.get_model(app_label, model_name)
    unified_index = connections[using].get_unified_index()
    index = unified_index.get_index(model)
    return model, index


@shared_task(bind=True)
def async_clear_index_model(self, model_label):
    """Clear Elasticsearch documents for a single index (model). Returns count cleared."""
    from haystack.constants import DJANGO_CT
    from haystack.utils import get_model_ct

    try:
        model, _ = _get_model_and_index(model_label)
        backend = connections["default"].get_backend()
        try:
            count_before = backend.conn.count(
                index=backend.index_name,
                body={"query": {"term": {DJANGO_CT: get_model_ct(model)}}},
            )["count"]
        except Exception:
            count_before = 0
        backend.clear(models=[model], commit=True)
        logger.info("Cleared search index for %s (%d documents).", model_label, count_before)
        return {"action": "clear", "model_label": model_label, "cleared": count_before}
    except Exception as e:
        logger.exception("Error clearing index for %s: %s", model_label, e)
        raise


@shared_task(bind=True)
def async_update_index_model(self, model_label):
    """Reindex a single model. Updates task state with progress; returns count indexed."""
    import time

    try:
        model, index = _get_model_and_index(model_label)
        backend = connections["default"].get_backend()
        qs = index.build_queryset(using="default")
        qs = qs.order_by("pk")
        total = qs.count()
        batch_size = getattr(backend, "batch_size", DEFAULT_BATCH_SIZE) or DEFAULT_BATCH_SIZE
        indexed = 0
        last_max_pk = None

        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            if last_max_pk is not None:
                current_qs = list(qs.filter(pk__gt=last_max_pk)[: end - start])
            else:
                current_qs = list(qs[start:end])

            if current_qs:
                last_max_pk = current_qs[-1].pk
            else:
                break

            for attempt in range(DEFAULT_MAX_RETRIES):
                try:
                    backend.update(index, current_qs, commit=True)
                    break
                except Exception as exc:
                    if attempt >= DEFAULT_MAX_RETRIES - 1:
                        raise
                    time.sleep(2 ** attempt)

            indexed += len(current_qs)
            self.update_state(
                state="PROGRESS",
                meta={"current": indexed, "total": total, "model_label": model_label},
            )
            reset_queries()

        logger.info("Reindexed %s: %d documents.", model_label, indexed)
        return {"action": "update", "model_label": model_label, "indexed": indexed, "total": total}
    except NotHandled:
        logger.exception("No search index for model %s.", model_label)
        raise
    except Exception as e:
        logger.exception("Error reindexing %s: %s", model_label, e)
        raise


@shared_task(bind=True)
def async_clean_and_reindex_model(self, model_label):
    """Clear then reindex a single model. Returns combined result."""
    try:
        clear_result = async_clear_index_model.apply(args=[model_label]).get()
        update_result = async_update_index_model.apply(args=[model_label]).get()
        return {
            "action": "clean_and_reindex",
            "model_label": model_label,
            "cleared": clear_result.get("cleared", 0),
            "indexed": update_result.get("indexed", 0),
            "total": update_result.get("total", 0),
        }
    except Exception as e:
        logger.exception("Error clean-and-reindex for %s: %s", model_label, e)
        raise
