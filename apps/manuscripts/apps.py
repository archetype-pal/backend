from django.apps import AppConfig
from django.conf import settings


class ManuscriptsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manuscripts"
    verbose_name = settings.APP_NAME_MANUSCRIPTS
