import os

from celery import Celery
from celery.signals import worker_process_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("archetype")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


def _setup_django():
    import django

    django.setup()


@app.on_after_configure.connect
def on_celery_configure(sender, **kwargs):
    _setup_django()


@worker_process_init.connect
def on_worker_process_init(sender, **kwargs):
    """Ensure Django apps are loaded in each worker process (for apps.get_model, etc.)."""
    _setup_django()
