"""Test helper: a Meilisearch API error built the way the SDK builds one."""

import json
from unittest.mock import MagicMock

from meilisearch.errors import MeilisearchApiError


def api_error(code: str) -> MeilisearchApiError:
    """A Meilisearch API error carrying *code*."""
    response = MagicMock()
    response.status_code = 400
    response.text = json.dumps({"message": f"simulated {code}", "code": code, "type": "invalid_request"})
    return MeilisearchApiError("", response)
