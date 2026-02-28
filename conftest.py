"""Shared pytest fixtures for the backend test suite."""

import os

import django
import pytest

# Configure Django before any test module or DRF import (needed when running pytest
# locally without Docker, so that rest_framework.test etc. can access settings).
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# When running pytest outside Docker, use SQLite so tests don't require Postgres.
# Settings will check this and override DATABASES when set.
if not os.path.exists("/.dockerenv"):
    os.environ["USE_SQLITE_FOR_TESTS"] = "1"

django.setup()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture(autouse=True)
def _temporary_media_root(settings, tmp_path):
    """Use writable temp media storage for tests creating files."""
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    settings.MEDIA_ROOT = media_root


@pytest.fixture
def authenticated_client(db):
    from rest_framework.test import APIClient

    from apps.users.tests.factories import UserFactory

    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def management_client(db):
    from rest_framework.test import APIClient

    from apps.users.tests.factories import SuperuserFactory

    user = SuperuserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client
