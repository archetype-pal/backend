"""Search domain value objects. No framework or Meilisearch imports."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SortSpec:
    """Sort: attribute + direction."""

    attribute: str
    ascending: bool = True

    def __str__(self) -> str:
        direction = "asc" if self.ascending else "desc"
        return f"{self.attribute}:{direction}"


@dataclass
class FilterSpec:
    """
    Structured filter criteria (engine-agnostic).
    - equal: dict of attribute -> value or list of values (OR within attribute)
    - not_equal: dict of attribute -> value
    - in: dict of attribute -> list of values
    - range: dict of attribute -> (min?, max?) for numeric
    - manuscript_date: optional min_date, max_date, at_most_or_least, date_diff
    """

    equal: dict[str, str | int | float | list[str | int | float]] = field(default_factory=dict)
    not_equal: dict[str, str | int | float] = field(default_factory=dict)
    in_: dict[str, list[str | int | float]] = field(default_factory=dict)
    range_: dict[str, tuple[int | float | None, int | float | None]] = field(default_factory=dict)
    # Manuscript-specific: date range and precision
    min_date: int | None = None
    max_date: int | None = None
    at_most_or_least: str | None = None  # "at most" | "at least"
    date_diff: int | None = None


@dataclass
class SearchQuery:
    """User intent: optional full-text q, filter, sort, pagination."""

    q: str = ""
    filter_spec: FilterSpec = field(default_factory=FilterSpec)
    sort_spec: SortSpec | None = None
    limit: int = 20
    offset: int = 0


# DTOs returned by use cases / ports
@dataclass
class SearchResult:
    """Result of SearchDocuments use case."""

    hits: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@dataclass
class FacetResult:
    """Result of GetFacets use case. Meilisearch-native shape."""

    facet_distribution: dict[str, dict[str, int]]
    facet_stats: dict[str, dict[str, float]] = field(default_factory=dict)
