from unittest.mock import MagicMock

import pytest

from apps.search.meilisearch.reader import MeilisearchIndexReader
from apps.search.meilisearch.writer import MeilisearchIndexWriter


@pytest.fixture
def mock_writer() -> MeilisearchIndexWriter:
    """A writer whose Meilisearch client is a MagicMock, so nothing leaves the process."""
    writer = MeilisearchIndexWriter()
    writer._client = MagicMock()
    return writer


@pytest.fixture
def mock_reader() -> MeilisearchIndexReader:
    reader = MeilisearchIndexReader()
    reader._client = MagicMock()
    return reader
