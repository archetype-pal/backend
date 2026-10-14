"""Shared check that a list endpoint's query count does not grow with its rows."""

from collections.abc import Callable

from django.db import connection
from django.test.utils import CaptureQueriesContext


def assert_query_count_constant(client, url: str, add_rows: Callable[[int], object], batch: int = 4) -> None:
    """Add `batch` rows, count the queries of a GET, add as many again, and expect the same count."""

    def count() -> int:
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url)
        assert response.status_code == 200, response.content
        return len(queries.captured_queries)

    add_rows(batch)
    few = count()
    add_rows(batch)
    many = count()
    assert many == few, f"query count grew with row count: {few} -> {many}"
