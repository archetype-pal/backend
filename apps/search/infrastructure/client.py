"""Meilisearch client factory. Used only by infrastructure (adapters)."""

from django.conf import settings

_client = None


def get_meilisearch_client():
    """Return a singleton Meilisearch Client. Thread-safe for Django's request model."""
    global _client
    if _client is None:
        from meilisearch import Client

        url = getattr(settings, "MEILISEARCH_URL", "http://localhost:7700")
        api_key = getattr(settings, "MEILISEARCH_API_KEY") or None
        _client = Client(url=url, api_key=api_key)
    return _client
