import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def async_update_index(model_names=None):
    logger.info("Starting asynchronous index update task.")
    call_command("update_index")
    logger.info("Asynchronous index update task completed.")
