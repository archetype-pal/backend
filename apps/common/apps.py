from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"

    def ready(self) -> None:
        from apps.common.audit import register_audited_models

        from .models import SiteLabel

        register_audited_models(SiteLabel)
