from django.apps import AppConfig


class DiplomaticConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.diplomatic"
    verbose_name = "Diplomatic"

    def ready(self) -> None:
        # Importing the pipeline modules is what puts them in the registry.
        # Done here rather than in `pipelines/__init__` because they import
        # models, and nothing may touch the model registry before the app
        # registry is populated.
        from apps.diplomatic.pipelines import curation, extraction, formulae, translation  # noqa: F401
