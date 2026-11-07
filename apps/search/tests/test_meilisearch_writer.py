from types import SimpleNamespace
from unittest.mock import MagicMock, call

from meilisearch.errors import MeilisearchApiError, MeilisearchError
import pytest

from apps.search.meilisearch.client import index_uid
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.tests.meili_errors import api_error
from apps.search.types import IndexType
from apps.vision.services import glyph_search


def _task(status: str, code: str | None = None):
    return SimpleNamespace(status=status, error={"code": code} if code else None)


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
        client.delete_index.side_effect = api_error("index_not_found")

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
        client.delete_index.side_effect = api_error("invalid_api_key")

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
            _task("succeeded"),  # the glyph embedder, on its own
        ]

        _writer(client).prepare_build_index(IndexType.GRAPHS)

        # Through index_uid: the deployment (and each xdist worker) prefixes the index name.
        staging_uid = f"{index_uid(IndexType.GRAPHS)}{MeilisearchIndexWriter.BUILD_SUFFIX}"
        client.create_index.assert_called_once_with(staging_uid, {"primaryKey": "id"})


class TestEmbedder:
    """The graphs index searches by each glyph's vector, which the documents bring with them."""

    def test_is_set_on_its_own_after_the_other_settings_landed(self):
        client = MagicMock()
        client.wait_for_task.return_value = _task("succeeded")
        index = client.index.return_value
        index.update_typo_tolerance.return_value = SimpleNamespace(task_uid=5)
        index.update_embedders.return_value = SimpleNamespace(task_uid=6)

        _writer(client)._apply_index_settings("graphs", IndexType.GRAPHS)

        index.update_embedders.assert_called_once_with(
            {"glyph": {"source": "userProvided", "dimensions": glyph_search.DIMENSIONS}}
        )
        names = [name for name, _, _ in client.mock_calls]
        settings_landed = names.index("wait_for_task")
        assert client.mock_calls[settings_landed].args == (5,)
        assert names.index("index().update_embedders") > settings_landed
        assert client.mock_calls[-1] == call.wait_for_task(6, timeout_in_ms=MeilisearchIndexWriter.TASK_TIMEOUT_MS)

    def test_an_index_of_documents_without_vectors_keeps_its_other_settings_and_says_to_reindex(self, caplog):
        client = MagicMock()
        client.wait_for_task.side_effect = [_task("succeeded"), _task("failed", "vector_embedding_error")]

        _writer(client)._apply_index_settings("graphs", IndexType.GRAPHS)

        assert "reindex it" in caplog.text

    def test_any_other_failure_raises(self):
        client = MagicMock()
        client.wait_for_task.side_effect = [_task("succeeded"), _task("failed", "invalid_settings_embedders")]

        with pytest.raises(MeilisearchError, match="invalid_settings_embedders"):
            _writer(client)._apply_index_settings("graphs", IndexType.GRAPHS)

    def test_an_index_without_vectors_is_given_no_embedder(self):
        client = MagicMock()
        client.wait_for_task.return_value = _task("succeeded")

        _writer(client)._apply_index_settings("texts", IndexType.TEXTS)

        client.index.return_value.update_embedders.assert_not_called()
