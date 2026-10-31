"""Reading flags out of a request's query string."""

from django.http import QueryDict

TRUE_VALUES = {"1", "true", "yes"}


def query_flag(params: QueryDict, name: str) -> bool:
    """Whether `?name=` is set to one of `TRUE_VALUES` (case-insensitive); missing or anything else is False."""
    return (params.get(name) or "").strip().lower() in TRUE_VALUES
