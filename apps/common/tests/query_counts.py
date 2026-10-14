"""Shared check that a list endpoint's query count does not grow with its rows."""

from collections.abc import Callable

from django.db import connection
from django.test.utils import CaptureQueriesContext


def assert_query_count_constant(client, url: str, add_rows: Callable[[int], object], batch: int = 4) -> None:
    """Add `batch` rows, count the queries of a GET, add as many again, and expect the same count."""

    def queries() -> list[str]:
        with CaptureQueriesContext(connection) as captured:
            response = client.get(url)
        assert response.status_code == 200, response.content
        return [query["sql"] for query in captured.captured_queries]

    add_rows(batch)
    few = queries()
    add_rows(batch)
    many = queries()
    extra = "\n".join(sql for sql in many if sql not in few) or "(none; a query repeats)"
    assert len(many) == len(few), f"query count grew with row count: {len(few)} -> {len(many)}; new queries:\n{extra}"
