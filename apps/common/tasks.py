from celery import shared_task
from django.apps import apps
from django.core.paginator import Paginator
from haystack import connections
from haystack.constants import DEFAULT_ALIAS


@shared_task
def async_update_index(model_names=None):
    """
    Update search index asynchronously using Celery
    :param model_names: Optional list of specific models to index
    """
    # Get unified index
    unified_index = connections[DEFAULT_ALIAS].get_unified_index()

    if model_names:
        # If specific models requested, only index those
        models = [apps.get_model(m) for m in model_names]
    else:
        # Get all registered models in the index
        models = unified_index.get_indexed_models()

    for model in models:
        # Get the model's indexable objects
        qs = model.objects.all().order_by(model._meta.pk.name)

        # Use Django's Paginator for batching
        paginator = Paginator(qs, 100)  # Process 100 objects at a time

        for page_num in range(1, paginator.num_pages + 1):
            batch = paginator.page(page_num).object_list
            update_batch.delay(model._meta.label, [obj.pk for obj in batch])

    return f"Indexing tasks dispatched for {len(models)} models"


@shared_task
def update_batch(model_label, pk_list):
    """
    Update index for a batch of objects
    :param model_label: Model label (e.g., 'app.Model')
    :param pk_list: List of primary keys to index
    """
    model = apps.get_model(model_label)
    connection = connections[DEFAULT_ALIAS]
    backend = connection.get_backend()
    index = connection.get_unified_index().get_index(model)

    # Get the objects for this batch
    objects = model.objects.filter(pk__in=pk_list)

    # Update index for these objects
    if objects:
        backend.update(index, objects)

    return f"Indexed {len(objects)} objects of {model_label}"
