"""The reindex single-flight lock, against an in-memory cache standing in for Redis."""

from django.test import override_settings
import pytest

from apps.search.services import ReindexInProgressError, reindex_lock
from apps.search.types import IndexType

LOCMEM_LOCKS = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "locks": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "reindex-lock-tests"},
}


@override_settings(CACHES=LOCMEM_LOCKS)
def test_the_lock_is_held_for_the_block_and_released_even_on_error():
    with reindex_lock(IndexType.SCRIBES):
        with pytest.raises(ReindexInProgressError):
            with reindex_lock(IndexType.SCRIBES):
                pass
        with reindex_lock(IndexType.HANDS):  # another index is unaffected
            pass

    with pytest.raises(RuntimeError):
        with reindex_lock(IndexType.SCRIBES):
            raise RuntimeError("boom")
    with reindex_lock(IndexType.SCRIBES):  # released by the failed run
        pass


@override_settings(CACHES=LOCMEM_LOCKS)
def test_a_contended_run_does_not_release_the_holders_lock():
    with reindex_lock(IndexType.SCRIBES):
        for _ in range(2):
            with pytest.raises(ReindexInProgressError):
                with reindex_lock(IndexType.SCRIBES):
                    pass


def test_lock_degrades_to_noop_when_the_backend_is_unavailable():
    # The test settings point `locks` at a Redis that is not running.
    with reindex_lock(IndexType.SCRIBES):
        pass
