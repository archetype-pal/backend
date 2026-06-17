"""Tests for the search reindex single-flight lock (H4)."""

from unittest.mock import patch

import pytest

from apps.search.services import ReindexInProgressError, reindex_lock
from apps.search.types import IndexType


def test_lock_acquires_and_releases_on_clean_exit():
    with patch("apps.search.services.caches") as caches_mock:
        cache = caches_mock.__getitem__.return_value
        cache.add.return_value = True
        with reindex_lock(IndexType.SCRIBES):
            pass
        cache.add.assert_called_once()
        cache.delete.assert_called_once()


def test_lock_releases_even_when_body_raises():
    with patch("apps.search.services.caches") as caches_mock:
        cache = caches_mock.__getitem__.return_value
        cache.add.return_value = True
        with pytest.raises(RuntimeError):
            with reindex_lock(IndexType.SCRIBES):
                raise RuntimeError("boom")
        cache.delete.assert_called_once()


def test_contended_lock_raises_and_does_not_release():
    with patch("apps.search.services.caches") as caches_mock:
        cache = caches_mock.__getitem__.return_value
        cache.add.return_value = False  # already held
        with pytest.raises(ReindexInProgressError):
            with reindex_lock(IndexType.SCRIBES):
                pass
        # Must NOT delete a key it didn't acquire (that would free the other run's lock).
        cache.delete.assert_not_called()


def test_lock_degrades_to_noop_when_backend_unavailable():
    with patch("apps.search.services.caches") as caches_mock:
        caches_mock.__getitem__.side_effect = Exception("redis down")
        entered = False
        with reindex_lock(IndexType.SCRIBES):
            entered = True
        assert entered, "lock must not block reindex when the lock backend is unavailable"
