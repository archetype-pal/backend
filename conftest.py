"""Shared pytest fixtures for the backend test suite."""

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
