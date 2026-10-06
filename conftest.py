"""Shared pytest fixtures for the backend test suite."""

import os

import django
import pytest

# Configure Django before any test module or DRF import (needed when running pytest
# locally without Docker, so that rest_framework.test etc. can access settings).
# Compose env interpolation can set DJANGO_SETTINGS_MODULE to an empty string, which
# breaks django.setup(); treat empty values as unset.
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

# When running pytest outside Docker, use SQLite so tests don't require Postgres.
# Settings will check this and override DATABASES when set.
if not os.path.exists("/.dockerenv"):
    os.environ["USE_SQLITE_FOR_TESTS"] = "1"

django.setup()

from django.conf import settings  # noqa: E402

# UserFactory calls set_password(), and the production PBKDF2 hasher is slow by
# design — a large share of the suite's run time. No test depends on the hash
# format, so tests use a fast one.
settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Under pytest-xdist each worker gets its own test database; give it its own
# Meilisearch indexes too, since the search API tests write to the live service.
if xdist_worker := os.environ.get("PYTEST_XDIST_WORKER"):
    settings.MEILISEARCH_INDEX_PREFIX = f"{settings.MEILISEARCH_INDEX_PREFIX}{xdist_worker}_"


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
