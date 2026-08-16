"""Meilisearch client factory."""

from django.conf import settings

_client = None

# Without this the SDK passes timeout=None to requests, which blocks forever on
# a Meilisearch that accepts the connection and never answers. Generous rather
# than snappy: the same client posts 1000-document indexing batches.
REQUEST_TIMEOUT_SECONDS = 30


def get_meilisearch_client():
    """Return a singleton Meilisearch Client. Thread-safe for Django's request model."""
    global _client
    if _client is None:
        from meilisearch import Client

        api_key = settings.MEILISEARCH_API_KEY or None
        _client = Client(url=settings.MEILISEARCH_URL, api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    return _client
