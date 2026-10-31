from django.apps import AppConfig


class AnnotationsConfig(AppConfig):
    name = "apps.annotations"

    def ready(self) -> None:
        from apps.common.audit import register_audited_models

        from .models import Graph

        register_audited_models(Graph)
