from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = "apps.search"
    verbose_name = "Search & Discovery"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (registers the MsDescArea reindex receivers)
