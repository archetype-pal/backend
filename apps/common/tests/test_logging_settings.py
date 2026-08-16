"""LOGGING wiring in config/settings.py, which is import-time module-level code."""

import importlib
import logging.config
from unittest import mock

from django.conf import settings
import pytest

import config.settings


@pytest.fixture
def reload_settings(monkeypatch):
    """Re-execute config/settings.py under patched env, with os.makedirs stubbed so
    file logging can be exercised without a writable /var/log/app."""

    def _reload(**environ):
        monkeypatch.delenv("LOG_IN_FILE", raising=False)
        monkeypatch.delenv("APP_LOG_LEVEL", raising=False)
        for key, value in environ.items():
            monkeypatch.setenv(key, value)
        with mock.patch("os.makedirs"):
            return importlib.reload(config.settings)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config.settings)
    logging.config.dictConfig(settings.LOGGING)


def test_file_logging_is_off_unless_opted_in(reload_settings):
    module = reload_settings()

    assert "file" not in module.LOGGING["handlers"]
    assert module.LOGGING["loggers"]["django"]["handlers"] == ["console"]


def test_apps_logger_defaults_to_info(reload_settings):
    module = reload_settings()

    assert module.LOGGING["loggers"]["apps"]["level"] == "INFO"


def test_enabling_file_logging_wires_every_logger(reload_settings):
    module = reload_settings(LOG_IN_FILE="True")

    assert "file" in module.LOGGING["handlers"]
    for name in ("django", "django.request", "apps"):
        assert "file" in module.LOGGING["loggers"][name]["handlers"]


def test_file_handler_does_not_open_the_log_at_configuration_time(reload_settings, tmp_path):
    module = reload_settings(LOG_IN_FILE="True")
    module.LOGGING["handlers"]["file"]["filename"] = str(tmp_path / "absent" / "app.log")

    logging.config.dictConfig(module.LOGGING)  # raises without delay=True
