"""Central registry for search index metadata and strategy wiring."""

from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.db.models import QuerySet

from apps.search.contracts import IndexDocumentBuilder
from apps.search.documents import BUILDERS_MANY
from apps.search.index_metadata import (
    DEFAULT_FACET_ATTRIBUTES,
    FILTERABLE_ATTRIBUTES,
    SEARCHABLE_ATTRIBUTES,
    SORTABLE_ATTRIBUTES,
)
from apps.search.types import IndexType


@dataclass(frozen=True)
class IndexRegistration:
    index_type: IndexType
    url_segment: str
    model_label: tuple[str, str]
    builder: IndexDocumentBuilder
    filterable_attributes: list[str]
    sortable_attributes: list[str]
    default_facet_attributes: list[str]
    searchable_attributes: list[str]


def _optimize_queryset(index_type: IndexType, queryset: QuerySet[Any]) -> QuerySet[Any]:
    if index_type == IndexType.ITEM_PARTS:
        return queryset.select_related(
            "current_item__repository",
            "historical_item__date",
            "historical_item__format",
        ).prefetch_related("historical_item__catalogue_numbers", "images")
    if index_type == IndexType.ITEM_IMAGES:
        return queryset.select_related(
            "item_part__current_item__repository",
            "item_part__historical_item__date",
        ).prefetch_related(
            "graphs__positions",
            "graphs__components",
            "graphs__graphcomponent_set__component",
            "graphs__graphcomponent_set__features",
        )
    if index_type == IndexType.HANDS:
        return queryset.select_related(
            "item_part__current_item__repository",
            "item_part__historical_item__date",
            "date",
        ).prefetch_related("item_part__historical_item__catalogue_numbers")
    if index_type == IndexType.GRAPHS:
        return queryset.select_related(
            "item_image__item_part__current_item__repository",
            "item_image__item_part__historical_item__date",
            "allograph__character",
            "hand",
        ).prefetch_related(
            "positions",
            "components",
            "graphcomponent_set__component",
            "graphcomponent_set__features",
        )
    if index_type in {IndexType.TEXTS, IndexType.CLAUSES, IndexType.PEOPLE, IndexType.PLACES}:
        return queryset.select_related(
            "item_image__item_part__current_item__repository",
            "item_image__item_part__historical_item__date",
        ).prefetch_related("item_image__item_part__historical_item__catalogue_numbers")
    return queryset


MODEL_LABELS: dict[IndexType, tuple[str, str]] = {
    IndexType.ITEM_PARTS: ("manuscripts", "ItemPart"),
    IndexType.ITEM_IMAGES: ("manuscripts", "ItemImage"),
    IndexType.SCRIBES: ("scribes", "Scribe"),
    IndexType.HANDS: ("scribes", "Hand"),
    IndexType.GRAPHS: ("annotations", "Graph"),
    IndexType.TEXTS: ("manuscripts", "ImageText"),
    IndexType.CLAUSES: ("manuscripts", "ImageText"),
    IndexType.PEOPLE: ("manuscripts", "ImageText"),
    IndexType.PLACES: ("manuscripts", "ImageText"),
}


INDEX_REGISTRY: dict[IndexType, IndexRegistration] = {
    index_type: IndexRegistration(
        index_type=index_type,
        url_segment=index_type.value.replace("_", "-"),
        model_label=MODEL_LABELS[index_type],
        builder=BUILDERS_MANY[index_type],
        filterable_attributes=FILTERABLE_ATTRIBUTES.get(index_type, []),
        sortable_attributes=SORTABLE_ATTRIBUTES.get(index_type, []),
        default_facet_attributes=DEFAULT_FACET_ATTRIBUTES.get(index_type, []),
        searchable_attributes=SEARCHABLE_ATTRIBUTES.get(index_type, []),
    )
    for index_type in IndexType
}

URL_SEGMENT_TO_INDEX_TYPE: dict[str, IndexType] = {
    registration.url_segment: registration.index_type for registration in INDEX_REGISTRY.values()
}


def get_registration(index_type: IndexType) -> IndexRegistration:
    return INDEX_REGISTRY[index_type]


def get_registration_by_segment(url_segment: str) -> IndexRegistration | None:
    index_type = URL_SEGMENT_TO_INDEX_TYPE.get(url_segment)
    if index_type is None:
        return None
    return INDEX_REGISTRY[index_type]


def get_queryset_for_index(index_type: IndexType) -> QuerySet[Any]:
    registration = get_registration(index_type)
    app_label, model_name = registration.model_label
    model = apps.get_model(app_label, model_name)
    queryset = model.objects.all().order_by("pk")
    return _optimize_queryset(index_type, queryset)
