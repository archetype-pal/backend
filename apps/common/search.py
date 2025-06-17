from apps.common.tasks import async_update_index


def update_search_index(models=None):
    """
    Trigger asynchronous index update
    :param models: Optional list of model names to index (e.g., ['manuscripts.ItemPart'])
    :return: Celery task object
    """
    task = async_update_index.delay(models)
    return task