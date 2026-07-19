"""Single declarative source of truth for every search index.

Each :class:`IndexType` maps to exactly one :class:`IndexRegistration` holding
*all* of its configuration — model, document builder, the Meilisearch attribute
lists (filterable/sortable/facet/searchable), the ORM prefetch spec, and the
optional one-to-many count extractor used by admin stats. Adding or changing an
index is a single-entry edit here; nothing about an index lives anywhere else.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.db.models import QuerySet

from apps.search.contracts import IndexDocumentBuilder
from apps.search.documents import (
    build_clause_documents,
    build_graph_document,
    build_hand_document,
    build_item_image_document,
    build_item_part_document,
    build_person_documents,
    build_place_documents,
    build_scribe_document,
    build_text_document,
    normalize_builder,
)
from apps.search.documents.dpt_parser import (
    extract_clauses,
    extract_people_detailed,
    extract_places_detailed,
)
from apps.search.types import IndexType


@dataclass(frozen=True)
class IndexRegistration:
    """The complete configuration for one search index."""

    index_type: IndexType
    model_label: tuple[str, str]
    builder: IndexDocumentBuilder
    filterable_attributes: list[str]
    sortable_attributes: list[str]
    default_facet_attributes: list[str]
    searchable_attributes: list[str]
    select_related: tuple[str, ...] = ()
    prefetch_related: tuple[str, ...] = ()
    # Filter kwargs applied to the index queryset. Used to keep the legacy
    # migration sentinel out of search: the DigiPal import created ItemPart
    # pk=-1 ("Created for all the nulls contained in public.digipal_image")
    # to park orphaned images, which otherwise surfaces as a bogus manuscript
    # card whose links point at /manuscripts/-1.
    queryset_filter: dict[str, Any] | None = None
    # ImageText-derived indexes fan one row out to N documents; this returns the
    # expected document count for a given `content` string (admin in-sync stats).
    count_extractor: Callable[[str], int] | None = None

    @property
    def url_segment(self) -> str:
        """URL path segment for this index (e.g. ``item-parts``)."""
        return self.index_type.value.replace("_", "-")


# ImageText-derived indexes (texts/clauses/people/places) share one prefetch spec.
_TEXT_DERIVED_SELECT_RELATED = (
    "item_image__item_part__current_item__repository",
    "item_image__item_part__historical_item__date",
)
_TEXT_DERIVED_PREFETCH = ("item_image__item_part__historical_item__catalogue_numbers__catalogue",)


INDEX_REGISTRY: dict[IndexType, IndexRegistration] = {
    IndexType.ITEM_PARTS: IndexRegistration(
        index_type=IndexType.ITEM_PARTS,
        model_label=("manuscripts", "ItemPart"),
        builder=normalize_builder(build_item_part_document),
        select_related=(
            "current_item__repository",
            "historical_item__date",
            "historical_item__format",
        ),
        prefetch_related=("historical_item__catalogue_numbers__catalogue", "images"),
        queryset_filter={"pk__gte": 1},
        filterable_attributes=[
            "id",
            "repository_name",
            "repository_city",
            "shelfmark",
            "catalogue_numbers",
            "date",
            "date_min",
            "date_max",
            "type",
            "format",
            "number_of_images",
            "image_availability",
        ],
        sortable_attributes=[
            "id",
            "repository_name",
            "repository_city",
            "shelfmark",
            "catalogue_numbers",
            "type",
            "number_of_images",
            "date_min",
            "date_max",
        ],
        default_facet_attributes=[
            "image_availability",
            "type",
            "repository_city",
            "repository_name",
            "format",
            "date_min",
            "date_max",
        ],
        searchable_attributes=[
            "display_label",
            "repository_name",
            "repository_city",
            "shelfmark",
            "catalogue_numbers",
            "type",
        ],
    ),
    IndexType.ITEM_IMAGES: IndexRegistration(
        index_type=IndexType.ITEM_IMAGES,
        model_label=("manuscripts", "ItemImage"),
        builder=normalize_builder(build_item_image_document),
        select_related=(
            "item_part__current_item__repository",
            "item_part__historical_item__date",
        ),
        prefetch_related=(
            "graphs__positions",
            "graphs__components",
            "graphs__graphcomponent_set__component",
            "graphs__graphcomponent_set__features",
        ),
        queryset_filter={"item_part_id__gte": 1},
        filterable_attributes=[
            "id",
            "item_part",
            "locus",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date",
            "type",
            "number_of_annotations",
            "components",
            "features",
            "component_features",
            "positions",
            "tags",
        ],
        sortable_attributes=[
            "id",
            "repository_name",
            "repository_city",
            "shelfmark",
            "type",
            "number_of_annotations",
        ],
        default_facet_attributes=[
            "locus",
            "type",
            "repository_city",
            "repository_name",
            "components",
            "features",
            "component_features",
            "tags",
        ],
        searchable_attributes=["locus", "repository_name", "shelfmark", "components", "features", "tags"],
    ),
    IndexType.SCRIBES: IndexRegistration(
        index_type=IndexType.SCRIBES,
        model_label=("scribes", "Scribe"),
        builder=normalize_builder(build_scribe_document),
        filterable_attributes=["id", "name", "period", "scriptorium"],
        sortable_attributes=["id", "name", "scriptorium"],
        default_facet_attributes=["scriptorium"],
        searchable_attributes=["name", "scriptorium"],
    ),
    IndexType.HANDS: IndexRegistration(
        index_type=IndexType.HANDS,
        model_label=("scribes", "Hand"),
        builder=normalize_builder(build_hand_document),
        select_related=(
            "item_part__current_item__repository",
            "item_part__historical_item__date",
            "date",
        ),
        prefetch_related=("item_part__historical_item__catalogue_numbers__catalogue",),
        filterable_attributes=[
            "id",
            "name",
            "place",
            "repository_name",
            "repository_city",
            "shelfmark",
            "catalogue_numbers",
            "date",
        ],
        sortable_attributes=[
            "id",
            "name",
            "repository_name",
            "repository_city",
            "shelfmark",
            "place",
            "catalogue_numbers",
        ],
        default_facet_attributes=["repository_city", "repository_name", "place"],
        searchable_attributes=["name", "place", "description", "repository_name", "shelfmark"],
    ),
    IndexType.GRAPHS: IndexRegistration(
        index_type=IndexType.GRAPHS,
        model_label=("annotations", "Graph"),
        builder=normalize_builder(build_graph_document),
        select_related=(
            "item_image__item_part__current_item__repository",
            "item_image__item_part__historical_item__date",
            "allograph__character",
            "hand",
        ),
        prefetch_related=(
            "positions",
            "components",
            "graphcomponent_set__component",
            "graphcomponent_set__features",
        ),
        filterable_attributes=[
            "id",
            "image_iiif",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date",
            "place",
            "hand_name",
            "components",
            "features",
            "component_features",
            "positions",
            "allograph",
            "character",
            "character_type",
            "is_annotated",
        ],
        sortable_attributes=["id", "repository_name", "repository_city", "shelfmark", "allograph"],
        default_facet_attributes=[
            "repository_city",
            "repository_name",
            "allograph",
            "character",
            "character_type",
            "components",
            "features",
            "component_features",
            "positions",
        ],
        searchable_attributes=[
            "display_label",
            "repository_name",
            "shelfmark",
            "allograph",
            "character",
            "hand_name",
            "components",
        ],
    ),
    IndexType.TEXTS: IndexRegistration(
        index_type=IndexType.TEXTS,
        model_label=("manuscripts", "ImageText"),
        builder=normalize_builder(build_text_document),
        select_related=_TEXT_DERIVED_SELECT_RELATED,
        prefetch_related=_TEXT_DERIVED_PREFETCH,
        filterable_attributes=[
            "id",
            "repository_name",
            "repository_city",
            "shelfmark",
            "text_type",
            "date",
            "date_min",
            "date_max",
            "type",
            "status",
            "language",
            "places",
            "people",
        ],
        sortable_attributes=[
            "id",
            "repository_name",
            "repository_city",
            "shelfmark",
            "text_type",
            "date_min",
            "date_max",
        ],
        default_facet_attributes=[
            "text_type",
            "type",
            "repository_city",
            "repository_name",
            "status",
            "language",
            "date_min",
            "date_max",
            "places",
            "people",
        ],
        searchable_attributes=[
            "content",
            "repository_name",
            "shelfmark",
            "catalogue_numbers",
            "text_type",
            "places",
            "people",
        ],
    ),
    IndexType.CLAUSES: IndexRegistration(
        index_type=IndexType.CLAUSES,
        model_label=("manuscripts", "ImageText"),
        builder=normalize_builder(build_clause_documents),
        count_extractor=lambda content: len(extract_clauses(content)),
        select_related=_TEXT_DERIVED_SELECT_RELATED,
        prefetch_related=_TEXT_DERIVED_PREFETCH,
        filterable_attributes=[
            "id",
            "clause_type",
            "text_type",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date_min",
            "date_max",
            "type",
            "status",
        ],
        sortable_attributes=[
            "id",
            "clause_type",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date_min",
            "date_max",
        ],
        default_facet_attributes=[
            "clause_type",
            "text_type",
            "type",
            "repository_city",
            "repository_name",
            "status",
            "date_min",
            "date_max",
        ],
        searchable_attributes=["content", "clause_type", "repository_name", "shelfmark"],
    ),
    IndexType.PEOPLE: IndexRegistration(
        index_type=IndexType.PEOPLE,
        model_label=("manuscripts", "ImageText"),
        builder=normalize_builder(build_person_documents),
        count_extractor=lambda content: len(extract_people_detailed(content)),
        select_related=_TEXT_DERIVED_SELECT_RELATED,
        prefetch_related=_TEXT_DERIVED_PREFETCH,
        filterable_attributes=[
            "id",
            "name",
            "person_type",
            "ref",
            "text_type",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date_min",
            "date_max",
            "type",
            "status",
        ],
        sortable_attributes=[
            "id",
            "name",
            "person_type",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date_min",
            "date_max",
        ],
        default_facet_attributes=[
            "person_type",
            "text_type",
            "type",
            "repository_city",
            "repository_name",
            "status",
            "date_min",
            "date_max",
        ],
        searchable_attributes=["name", "person_type", "ref", "repository_name", "shelfmark"],
    ),
    IndexType.PLACES: IndexRegistration(
        index_type=IndexType.PLACES,
        model_label=("manuscripts", "ImageText"),
        builder=normalize_builder(build_place_documents),
        count_extractor=lambda content: len(extract_places_detailed(content)),
        select_related=_TEXT_DERIVED_SELECT_RELATED,
        prefetch_related=_TEXT_DERIVED_PREFETCH,
        filterable_attributes=[
            "id",
            "name",
            "place_type",
            "ref",
            "text_type",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date_min",
            "date_max",
            "type",
            "status",
        ],
        sortable_attributes=[
            "id",
            "name",
            "place_type",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date_min",
            "date_max",
        ],
        default_facet_attributes=[
            "place_type",
            "text_type",
            "type",
            "repository_city",
            "repository_name",
            "status",
            "date_min",
            "date_max",
        ],
        searchable_attributes=["name", "place_type", "ref", "repository_name", "shelfmark"],
    ),
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
    model = apps.get_model(*registration.model_label)
    queryset = model.objects.all().order_by("pk")
    if registration.queryset_filter:
        queryset = queryset.filter(**registration.queryset_filter)
    if registration.select_related:
        queryset = queryset.select_related(*registration.select_related)
    if registration.prefetch_related:
        queryset = queryset.prefetch_related(*registration.prefetch_related)
    return queryset
