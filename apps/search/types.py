from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IndexType(StrEnum):
    """Named searchable collection; the value is the Meilisearch index uid."""

    ITEM_PARTS = "item_parts"
    ITEM_IMAGES = "item_images"
    SCRIBES = "scribes"
    HANDS = "hands"
    GRAPHS = "graphs"
    TEXTS = "texts"
    CLAUSES = "clauses"
    PEOPLE = "people"
    PLACES = "places"

    @property
    def segment(self) -> str:
        """The hyphenated form used in URLs, the CLI and task payloads (`item-parts`)."""
        return self.value.replace("_", "-")

    @classmethod
    def from_segment(cls, segment: str) -> IndexType:
        try:
            return cls(segment.replace("-", "_"))
        except ValueError:
            raise ValueError(f"Unknown index type: '{segment}'.") from None


@dataclass(frozen=True)
class SortSpec:
    attribute: str
    ascending: bool = True

    def __str__(self) -> str:
        """Meilisearch's `attribute:asc|desc` form."""
        return f"{self.attribute}:{'asc' if self.ascending else 'desc'}"


@dataclass
class FilterSpec:
    """
    Structured filter criteria (engine-agnostic).
    - equal: dict of attribute -> value or list of values (OR within attribute)
    - not_equal: dict of attribute -> value or list of values (multiple exclusions)
    - range: dict of attribute -> (min?, max?) for numeric
    - manuscript_date: optional min_date, max_date, at_most_or_least, date_diff
    - contains / starts_with: merged into full-text q + attributesToSearchOn in reader
    - empty / not_empty: Meilisearch IS NULL / IS NOT NULL
    - qb_expr: raw Meilisearch filter fragment from query builder (AND with other parts)
    """

    equal: dict[str, str | int | float | list[str | int | float]] = field(default_factory=dict)
    not_equal: dict[str, str | int | float | list[str | int | float]] = field(default_factory=dict)
    range_: dict[str, tuple[int | float | None, int | float | None]] = field(default_factory=dict)
    min_date: int | None = None
    max_date: int | None = None
    at_most_or_least: str | None = None  # "at most" | "at least"
    date_diff: int | None = None
    contains: dict[str, str] = field(default_factory=dict)
    starts_with: dict[str, str] = field(default_factory=dict)
    empty: list[str] = field(default_factory=list)
    not_empty: list[str] = field(default_factory=list)
    qb_expr: str | None = None


@dataclass
class SearchQuery:
    q: str = ""
    filter_spec: FilterSpec = field(default_factory=FilterSpec)
    sort_spec: SortSpec | None = None
    limit: int = 20
    offset: int = 0
    matching_strategy: str | None = None
    attributes_to_search_on: list[str] = field(default_factory=list)
    attributes_to_retrieve: list[str] = field(default_factory=list)
    # Meilisearch attributesToCrop / cropLength; the cropped, highlighted value
    # comes back in each hit's `_formatted`.
    attributes_to_crop: list[str] = field(default_factory=list)
    crop_length: int | None = None


@dataclass
class SearchResult:
    hits: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@dataclass
class FacetResult:
    facet_distribution: dict[str, dict[str, int]]
    facet_stats: dict[str, dict[str, float]] = field(default_factory=dict)
