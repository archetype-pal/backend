from django.apps import AppConfig


class ManuscriptsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manuscripts"
    verbose_name = "Manuscripts"

    def ready(self) -> None:
        from apps.common.audit import register_audited_models

        from .models import ImageText

        register_audited_models(ImageText)
