from django.apps import AppConfig


class ManuscriptsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manuscripts"
    verbose_name = "Manuscripts"

    def ready(self) -> None:
        from apps.common.audit import register_audited_models

        from . import signals  # noqa: F401  (registers the Graph pre_delete receiver)
        from .models import ImageText, ItemImage

        register_audited_models(ImageText, ItemImage)
