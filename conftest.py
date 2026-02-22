"""Shared pytest fixtures for the backend test suite."""

# Configure Django before any test module or DRF import (needed when running pytest
# locally without Docker, so that rest_framework.test etc. can access settings).
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# When running pytest outside Docker, use SQLite so tests don't require Postgres.
# Settings will check this and override DATABASES when set.
if not os.path.exists("/.dockerenv"):
    os.environ["USE_SQLITE_FOR_TESTS"] = "1"

import django

django.setup()

import pytest


@pytest.fixture
def api_client():
    """Unauthenticated API client."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def authenticated_client(db):
    """API client authenticated as a regular user."""
    from rest_framework.test import APIClient

    from apps.users.tests.factories import UserFactory

    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def admin_client(db):
    """API client authenticated as a staff/superuser (for admin API)."""
    from rest_framework.test import APIClient

    from apps.users.tests.factories import AdminFactory

    user = AdminFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client
