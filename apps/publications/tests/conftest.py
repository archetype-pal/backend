from django.core.cache import cache
import pytest


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    """Comment posting is throttled; each test starts with a clean history."""
    cache.clear()
