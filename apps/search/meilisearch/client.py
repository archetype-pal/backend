from typing import Any

from django.conf import settings
from meilisearch.errors import MeilisearchCommunicationError

from apps.search.types import IndexType

# Meilisearch cannot be reached: the client's own error, or the socket's (ConnectionError is an OSError).
MEILI_UNAVAILABLE = (MeilisearchCommunicationError, OSError)

_client = None

# The SDK otherwise passes timeout=None, which blocks forever on a Meilisearch
# that accepts the connection and never answers. Generous, not snappy: the same
# client posts 500-document indexing batches (`IndexingService.REINDEX_BATCH_SIZE`).
REQUEST_TIMEOUT_SECONDS = 30


def get_meilisearch_client():
    """Return a singleton Meilisearch Client. Thread-safe for Django's request model."""
    global _client
    if _client is None:
        from meilisearch import Client

        api_key = settings.MEILISEARCH_API_KEY or None
        _client = Client(url=settings.MEILISEARCH_URL, api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


def index_uid(index_type: IndexType) -> str:
    """The Meilisearch index name: the enum value, prefixed per deployment (`MEILISEARCH_INDEX_PREFIX`)."""
    return f"{settings.MEILISEARCH_INDEX_PREFIX or ''}{index_type.value}"


class MeilisearchAdapter:
    """Base for the reader and writer: a lazily-resolved client and the uid helper."""

    def __init__(self) -> None:
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_meilisearch_client()
        return self._client

    def _index_uid(self, index_type: IndexType) -> str:
        return index_uid(index_type)
