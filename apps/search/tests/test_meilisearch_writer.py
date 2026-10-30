from types import SimpleNamespace
from unittest.mock import MagicMock

from meilisearch.errors import MeilisearchApiError, MeilisearchError
import pytest

from apps.search.meilisearch.client import index_uid
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.types import IndexType


def _task(status: str, code: str | None = None):
    return SimpleNamespace(status=status, error={"code": code} if code else None)


def _api_error(code: str) -> MeilisearchApiError:
    err = MeilisearchApiError.__new__(MeilisearchApiError)
    err.code = code
    err.message = code
    return err


def _writer(client: MagicMock) -> MeilisearchIndexWriter:
    writer = MeilisearchIndexWriter()
    writer._client = client
    return writer


class TestDropIndexIfExists:
    def test_a_deletion_task_that_fails_with_index_not_found_is_treated_as_already_gone(self):
        client = MagicMock()
        client.delete_index.return_value = SimpleNamespace(task_uid=7)
        client.wait_for_task.return_value = _task("failed", "index_not_found")

        _writer(client)._drop_index_if_exists("graphs__build")

        client.wait_for_task.assert_called_once()

    def test_a_synchronous_index_not_found_is_treated_as_already_gone(self):
        client = MagicMock()
        client.delete_index.side_effect = _api_error("index_not_found")

        _writer(client)._drop_index_if_exists("graphs__build")

        client.wait_for_task.assert_not_called()

    def test_other_task_failures_still_raise(self):
        client = MagicMock()
        client.delete_index.return_value = SimpleNamespace(task_uid=7)
        client.wait_for_task.return_value = _task("failed", "internal")

        with pytest.raises(MeilisearchError, match="internal"):
            _writer(client)._drop_index_if_exists("graphs__build")

    def test_other_synchronous_errors_still_raise(self):
        client = MagicMock()
        client.delete_index.side_effect = _api_error("invalid_api_key")

        with pytest.raises(MeilisearchApiError):
            _writer(client)._drop_index_if_exists("graphs__build")


class TestPrepareBuildIndex:
    def test_a_missing_staging_index_does_not_abort_the_reindex(self):
        client = MagicMock()
        client.delete_index.return_value = SimpleNamespace(task_uid=1)
        client.create_index.return_value = SimpleNamespace(task_uid=2)
        client.wait_for_task.side_effect = [
            _task("failed", "index_not_found"),  # the drop of a staging index that never existed
            _task("succeeded"),  # create_index
            _task("succeeded"),  # the last settings task
        ]

        _writer(client).prepare_build_index(IndexType.GRAPHS)

        # Through index_uid: the deployment (and each xdist worker) prefixes the index name.
        staging_uid = f"{index_uid(IndexType.GRAPHS)}{MeilisearchIndexWriter.BUILD_SUFFIX}"
        client.create_index.assert_called_once_with(staging_uid, {"primaryKey": "id"})
