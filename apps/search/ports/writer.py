"""Port: index writer. Implemented by MeilisearchIndexWriter."""

from typing import Protocol

from apps.search.domain import IndexType


class IIndexWriter(Protocol):
    """Write/clear index. Used by Reindex use case."""

    def replace_documents(self, index_type: IndexType, documents: list[dict]) -> None:
        """Replace index contents with documents (create index if needed, set settings)."""
        ...

    def delete_all(self, index_type: IndexType) -> None:
        """Delete all documents in the index."""
        ...

    def get_stats(self, index_type: IndexType) -> dict:
        """Return index stats (e.g. number of documents) for admin."""
        ...
