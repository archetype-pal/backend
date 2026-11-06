from django.apps import AppConfig


class VisionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.vision"
    verbose_name = "Vision"

    def ready(self) -> None:
        from apps.annotations.services.proposals import proposal_accepted

        from .services.provenance import record_accepted_graph

        proposal_accepted.connect(record_accepted_graph, dispatch_uid="vision.record_accepted_graph")
