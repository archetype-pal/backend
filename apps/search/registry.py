"""Single declarative source of truth for every search index.

Each :class:`IndexType` maps to exactly one :class:`IndexRegistration` holding
*all* of its configuration — model, document builder, the Meilisearch attribute
lists (filterable/sortable/facet/searchable), the ORM prefetch spec, and the
optional per-row document count used by the admin stats. Adding or changing an
index is a single-entry edit here; nothing about an index lives anywhere else.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Model, Prefetch, QuerySet

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText, ItemImage, ItemPart
from apps.scribes.models import Hand, Scribe
from apps.search.contracts import SearchDocument
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
)
from apps.search.documents.dpt_parser import extract_clauses, extract_people_detailed, extract_places_detailed
from apps.search.types import IndexType


@dataclass(frozen=True)
class IndexRegistration:
    index_type: IndexType
    model: type[Model]
    # Turns one row into its document (a dict), documents (a list) or nothing (None).
    builder: Callable[[Any], Any]
    filterable_attributes: list[str]
    sortable_attributes: list[str]
    default_facet_attributes: list[str]
    searchable_attributes: list[str]
    select_related: tuple[str, ...] = ()
    prefetch_related: tuple[str | Prefetch, ...] = ()
    # Excludes rows from the index entirely: the DigiPal import's ItemPart
    # pk=-1 sentinel (which would surface as a card linking to /manuscripts/-1)
    # and non-public ImageText rows (`_PUBLIC_TEXT_STATUSES`).
    queryset_filter: dict[str, Any] | None = None
    # The inverse, for rules a filter cannot state without also dropping NULLs:
    # editorial graphs (`annotation_type` is nullable) — the index is public, and
    # editorial annotations are for signed-in users only.
    queryset_exclude: dict[str, Any] | None = None
    # Set where one row fans out to N documents, so their ids are derived
    # rather than the row's pk. Names the document field holding that pk, which
    # is how a sync deletes them. Must also be in `filterable_attributes`.
    parent_id_field: str | None = None
    # For fan-out indexes: how many documents a row produces, without building
    # them (the admin stats compare this sum with the live index count).
    documents_per_row: Callable[[Any], int] | None = None
    # `{attribute the API sorts on: attribute Meilisearch sorts on}`. The public
    # contract keeps the readable name; the index holds a key built for ordering
    # (`shelfmark` → `shelfmark_sort`, so `MS 2` comes before `MS 10`).
    sort_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def index_sortable_attributes(self) -> list[str]:
        """What the Meilisearch index is told to sort on: the public attributes plus the alias targets."""
        return list(dict.fromkeys([*self.sortable_attributes, *self.sort_aliases.values()]))

    def sort_attribute(self, attribute: str) -> str:
        return self.sort_aliases.get(attribute, attribute)

    def documents(self, obj: Any) -> list[SearchDocument]:
        result = self.builder(obj)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]


_TEXT_DERIVED_SELECT_RELATED = (
    "item_image__item_part__current_item__repository",
    "item_image__item_part__historical_item__date",
)
# The image's live graphs: what `documents.utils.region_coordinates` reads for the regions a text links to.
_TEXT_DERIVED_PREFETCH = (
    "item_image__item_part__historical_item__catalogue_numbers__catalogue",
    Prefetch("item_image__graphs", queryset=Graph.objects.only("id", "annotation", "annotation_type", "item_image_id")),
)
# Keeping drafts out of the index rather than filtering at query time means
# staff cannot search their own drafts. A status change moves the documents on
# the next sync, which rebuilds through this queryset.
_PUBLIC_TEXT_STATUSES = {"status__in": ImageText.PUBLIC_STATUSES}
# The manuscript context every text-derived document carries (see documents/utils.text_context).
_TEXT_CONTEXT_FILTERABLE = [
    "text_type",
    "repository_name",
    "repository_city",
    "shelfmark",
    "date_min",
    "date_max",
    "type",
    "status",
]
_TEXT_CONTEXT_SORTABLE = [
    "repository_name",
    "repository_city",
    "shelfmark",
    "locus",
    "type",
    "status",
    "date_min",
    "date_max",
]
# Facet order is the order the UI shows the rail in. `status` is filterable and sortable
# but not a facet: the public indexes only ever hold Live and Reviewed rows.
_TEXT_CONTEXT_FACETS = ["text_type", "type", "repository_city", "repository_name", "date_min", "date_max"]
# Every index that carries a manuscript's shelfmark sorts it in natural order.
_SHELFMARK_SORT = {"shelfmark": "shelfmark_sort"}


def _mentions_index(
    index_type: IndexType,
    *,
    builder: Callable[[Any], Any],
    type_field: str,
    extract: Callable[[str], list],
) -> IndexRegistration:
    """People and places: one document per `data-dpt` mention, identical but for the type field."""
    return IndexRegistration(
        index_type=index_type,
        model=ImageText,
        queryset_filter=_PUBLIC_TEXT_STATUSES,
        parent_id_field="image_text",
        builder=builder,
        documents_per_row=lambda obj: len(extract(obj.content or "")),
        select_related=_TEXT_DERIVED_SELECT_RELATED,
        prefetch_related=_TEXT_DERIVED_PREFETCH,
        filterable_attributes=["id", "image_text", "name", type_field, "ref", *_TEXT_CONTEXT_FILTERABLE],
        sortable_attributes=["id", "name", type_field, *_TEXT_CONTEXT_SORTABLE],
        sort_aliases=_SHELFMARK_SORT,
        default_facet_attributes=[type_field, *_TEXT_CONTEXT_FACETS],
        searchable_attributes=["name", type_field, "ref", "repository_name", "shelfmark"],
    )


INDEX_REGISTRY: dict[IndexType, IndexRegistration] = {
    IndexType.ITEM_PARTS: IndexRegistration(
        index_type=IndexType.ITEM_PARTS,
        model=ItemPart,
        builder=build_item_part_document,
        select_related=(
            "current_item__repository",
            "historical_item__date",
            "historical_item__format",
        ),
        prefetch_related=("historical_item__catalogue_numbers__catalogue", "images", "msdesc_areas"),
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
            # msDesc-derived (see documents/msdesc_parser.py) — multi-valued, not sortable.
            "material",
            "script",
            "deco_type",
            "seal_type",
            "seal_material",
            "origin_place",
        ],
        sortable_attributes=[
            "id",
            "repository_name",
            "repository_city",
            "shelfmark",
            "catalogue_numbers",
            "type",
            "format",
            "number_of_images",
            "date_min",
            "date_max",
        ],
        sort_aliases=_SHELFMARK_SORT,
        default_facet_attributes=[
            "image_availability",
            "type",
            "repository_city",
            "repository_name",
            "format",
            "date_min",
            "date_max",
            "material",
            "script",
            "deco_type",
            "seal_type",
            "seal_material",
            "origin_place",
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
        model=ItemImage,
        builder=build_item_image_document,
        select_related=(
            "item_part__current_item__repository",
            "item_part__historical_item__date",
        ),
        prefetch_related=(
            "graphs__positions",
            "graphs__components",
            "graphs__graphcomponent_set__component",
            "graphs__graphcomponent_set__features",
            "tags",
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
            "date_min",
            "date_max",
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
            "locus",
            "type",
            "number_of_annotations",
            "date_min",
            "date_max",
        ],
        sort_aliases=_SHELFMARK_SORT,
        default_facet_attributes=[
            "locus",
            "type",
            "repository_city",
            "repository_name",
            "date_min",
            "date_max",
            "components",
            "features",
            "component_features",
            "tags",
        ],
        searchable_attributes=[
            "display_label",
            "locus",
            "repository_name",
            "shelfmark",
            "components",
            "features",
            "tags",
        ],
    ),
    IndexType.SCRIBES: IndexRegistration(
        index_type=IndexType.SCRIBES,
        model=Scribe,
        builder=build_scribe_document,
        select_related=("period",),
        filterable_attributes=["id", "name", "period", "scriptorium"],
        sortable_attributes=["id", "name", "scriptorium"],
        default_facet_attributes=["scriptorium"],
        searchable_attributes=["name", "scriptorium"],
    ),
    IndexType.HANDS: IndexRegistration(
        index_type=IndexType.HANDS,
        model=Hand,
        builder=build_hand_document,
        select_related=(
            "item_part__current_item__repository",
            "item_part__historical_item__date",
            "date",
            "place",
        ),
        prefetch_related=("item_part__historical_item__catalogue_numbers__catalogue", "descriptions"),
        filterable_attributes=[
            "id",
            "name",
            "place",
            "repository_name",
            "repository_city",
            "shelfmark",
            "catalogue_numbers",
            "date",
            "date_min",
            "date_max",
        ],
        sortable_attributes=[
            "id",
            "name",
            "repository_name",
            "repository_city",
            "shelfmark",
            "place",
            "catalogue_numbers",
            "date_min",
            "date_max",
        ],
        sort_aliases=_SHELFMARK_SORT,
        default_facet_attributes=["repository_city", "repository_name", "place", "date_min", "date_max"],
        searchable_attributes=["name", "place", "description", "repository_name", "shelfmark"],
    ),
    IndexType.GRAPHS: IndexRegistration(
        index_type=IndexType.GRAPHS,
        model=Graph,
        builder=build_graph_document,
        queryset_exclude={"annotation_type": Graph.AnnotationType.EDITORIAL},
        select_related=(
            "item_image__item_part__current_item__repository",
            "item_image__item_part__historical_item__date",
            "allograph__character",
            "hand",
            "hand__scribe",
            "hand__place",
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
            "locus",
            "type",
            "date",
            "date_min",
            "date_max",
            "place",
            "hand_name",
            "scribe",
            "components",
            "features",
            "component_features",
            "positions",
            "allograph",
            "character",
            "character_type",
            "is_annotated",
        ],
        sortable_attributes=[
            "id",
            "repository_name",
            "repository_city",
            "shelfmark",
            "allograph",
            "character",
            "character_type",
            "hand_name",
            "scribe",
            "place",
            "locus",
            "type",
            "date_min",
            "date_max",
        ],
        sort_aliases=_SHELFMARK_SORT,
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
            "scribe",
            "components",
        ],
    ),
    IndexType.TEXTS: IndexRegistration(
        index_type=IndexType.TEXTS,
        model=ImageText,
        queryset_filter=_PUBLIC_TEXT_STATUSES,
        builder=build_text_document,
        select_related=_TEXT_DERIVED_SELECT_RELATED,
        prefetch_related=_TEXT_DERIVED_PREFETCH,
        filterable_attributes=["id", *_TEXT_CONTEXT_FILTERABLE, "date", "language", "places", "people"],
        sortable_attributes=["id", "text_type", "language", *_TEXT_CONTEXT_SORTABLE],
        sort_aliases=_SHELFMARK_SORT,
        default_facet_attributes=[
            "text_type",
            "type",
            "repository_city",
            "repository_name",
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
        model=ImageText,
        queryset_filter=_PUBLIC_TEXT_STATUSES,
        parent_id_field="image_text",
        builder=build_clause_documents,
        documents_per_row=lambda obj: len(extract_clauses(obj.content or "")),
        select_related=_TEXT_DERIVED_SELECT_RELATED,
        # Clauses additionally read the image's *other* text (see `_sibling_annotation_ids`).
        prefetch_related=(*_TEXT_DERIVED_PREFETCH, "item_image__texts"),
        filterable_attributes=["id", "image_text", "clause_type", *_TEXT_CONTEXT_FILTERABLE],
        sortable_attributes=["id", "clause_type", *_TEXT_CONTEXT_SORTABLE],
        sort_aliases=_SHELFMARK_SORT,
        default_facet_attributes=["clause_type", *_TEXT_CONTEXT_FACETS],
        searchable_attributes=["content", "clause_type", "repository_name", "shelfmark"],
    ),
    IndexType.PEOPLE: _mentions_index(
        IndexType.PEOPLE, builder=build_person_documents, type_field="person_type", extract=extract_people_detailed
    ),
    IndexType.PLACES: _mentions_index(
        IndexType.PLACES, builder=build_place_documents, type_field="place_type", extract=extract_places_detailed
    ),
}


def get_registration(index_type: IndexType) -> IndexRegistration:
    return INDEX_REGISTRY[index_type]


def get_queryset_for_index(index_type: IndexType) -> QuerySet[Any]:
    """The rows an index is built from, shaped for its builder's access pattern."""
    registration = get_registration(index_type)
    queryset = registration.model._default_manager.all().order_by("pk")
    if registration.queryset_filter:
        queryset = queryset.filter(**registration.queryset_filter)
    if registration.queryset_exclude:
        queryset = queryset.exclude(**registration.queryset_exclude)
    if registration.select_related:
        queryset = queryset.select_related(*registration.select_related)
    if registration.prefetch_related:
        queryset = queryset.prefetch_related(*registration.prefetch_related)
    return queryset
