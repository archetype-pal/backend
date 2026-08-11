import logging

from django.apps import AppConfig

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"

    def ready(self) -> None:
        from apps.common.audit import register_audited_models

        from .models import AppSettings, SiteLabel

        register_audited_models(SiteLabel, AppSettings)
        self._apply_runtime_log_level()

    def _apply_runtime_log_level(self) -> None:
        """Override the static APP_LOG_LEVEL default with an AppSettings value.

        LOG_LEVEL can't be read from AppSettings directly in config/settings.py:
        settings load before migrations are guaranteed to have run (the table
        may not exist yet on first boot) and before the DB may even be
        reachable, so any DB query at that point could crash startup. Doing the
        lookup here, in ready(), and guarding it with try/except handles both.
        """
        from .models import AppSettings

        try:
            setting = AppSettings.objects.filter(key="LOG_LEVEL", is_active=True).first()
        except Exception:
            # Table/DB not ready yet (e.g. pre-migrate first boot). Static
            # fallback from settings.py (APP_LOG_LEVEL) already applies.
            return

        if setting is None:
            return

        level = setting.value.strip().upper()
        if level not in _VALID_LOG_LEVELS:
            return

        # Both loggers: `apps` for application code, `django` for framework
        # logs, so the AppSettings override behaves like a global log level
        # rather than only affecting application-namespaced loggers.
        logging.getLogger("apps").setLevel(level)
        logging.getLogger("django").setLevel(level)
