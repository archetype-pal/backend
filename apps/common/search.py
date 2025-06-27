from celery import shared_task
from haystack.management.commands import update_index


@shared_task
def async_update_index(model_names=None):
    """
    Update search index asynchronously using Celery
    :param model_names: Optional list of specific models to index
    """
    kwargs = {
        "workers": 1,  # Disable multiprocessing by setting to 1
        "batchsize": 100,  # Number of items to index at once
        "remove": True,  # Remove items from index that dont exist in DB
    }

    if model_names:
        kwargs["models"] = model_names

    update_index.Command().handle(**kwargs)
    return "Indexing completed"
