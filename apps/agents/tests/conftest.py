"""Throttle state is process-global; tests must not inherit it.

DRF counts requests in the default cache, and pytest-django forces
`DEBUG = False`, so the agent's 10/hour bucket is live during the suite and
LocMemCache survives between tests. Without this, the seventh request in a file
is throttled by the first six and the failure looks like a bug in the agent.
"""

from django.core.cache import cache
import pytest


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    cache.clear()
    yield
    cache.clear()
