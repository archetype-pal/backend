import logging
from celery import shared_task
from django.apps import apps
from django.core.paginator import Paginator
from haystack import connections
from haystack.constants import DEFAULT_ALIAS

logger = logging.getLogger(__name__)


@shared_task
def async_update_index(model_names=None):
    """
    Update search index asynchronously using Celery
    :param model_names: Optional list of specific models to index
    """
    try:
        # Get unified index
        unified_index = connections[DEFAULT_ALIAS].get_unified_index()
        logger.info(f"Starting indexing with model_names: {model_names}")

        if model_names:
            # If specific models requested, only index those
            models = [apps.get_model(m) for m in model_names]
            logger.info(f"Models to index: {[m._meta.label for m in models]}")
        else:
            # Get all registered models in the index
            models = unified_index.get_indexed_models()
            logger.info(f"Found {len(models)} models to index: {[m._meta.label for m in models]}")

        tasks_dispatched = 0
        for model in models:
            # Get the model's indexable objects
            qs = model.objects.all().order_by(model._meta.pk.name)
            total_objects = qs.count()
            logger.info(f"Processing {model._meta.label} with {total_objects} objects")

            if total_objects > 0:
                # Use Django's Paginator for batching
                paginator = Paginator(qs, 100)  # Process 100 objects at a time

                for page_num in range(1, paginator.num_pages + 1):
                    batch = paginator.page(page_num).object_list
                    pk_list = [obj.pk for obj in batch]
                    update_batch.delay(model._meta.label, pk_list)
                    tasks_dispatched += 1
                    logger.info(f"Dispatched batch {page_num}/{paginator.num_pages} for {model._meta.label}")

        msg = f"Indexing tasks dispatched: {tasks_dispatched} batches for {len(models)} models"
        logger.info(msg)
        return msg
    except Exception as e:
        error_msg = f"Error in async_update_index: {str(e)}"
        logger.error(error_msg)
        raise


@shared_task
def update_batch(model_label, pk_list):
    """
    Update index for a batch of objects
    :param model_label: Model label (e.g., 'app.Model')
    :param pk_list: List of primary keys to index
    """
    try:
        model = apps.get_model(model_label)
        connection = connections[DEFAULT_ALIAS]
        backend = connection.get_backend()
        index = connection.get_unified_index().get_index(model)

        # Get the objects for this batch
        objects = model.objects.filter(pk__in=pk_list)
        count = len(objects)

        # Update index for these objects
        if objects:
            logger.info(f"Starting to index {count} objects of {model_label}")
            try:
                backend.update(index, objects)
                logger.info(f"✓ Successfully indexed {count} objects of {model_label}")
            except Exception as e:
                logger.error(f"Backend update failed for {model_label}: {str(e)}")
                raise
        else:
            logger.warning(f"No objects found for {model_label} with PKs: {pk_list}")

        return f"Indexed {count} objects of {model_label}"
    except Exception as e:
        error_msg = f"Error indexing {model_label}: {str(e)}"
        logger.error(error_msg)
        raise
