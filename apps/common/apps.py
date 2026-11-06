from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"

    def ready(self) -> None:
        from apps.common.audit import register_audited_models

        from .models import AppSettings, SiteLabel

        register_audited_models(SiteLabel, AppSettings)
