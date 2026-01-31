"""Meilisearch index settings per IndexType. Used by writer and reader."""

from apps.search.domain import IndexType

# All attributes that can be used in filter or facet must be here.
FILTERABLE_ATTRIBUTES: dict[IndexType, list[str]] = {
    IndexType.ITEM_PARTS: [
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
    IndexType.ITEM_IMAGES: [
        "id",
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
    ],
    IndexType.SCRIBES: [
        "id",
        "name",
        "period",
        "scriptorium",
    ],
    IndexType.HANDS: [
        "id",
        "name",
        "place",
        "repository_name",
        "repository_city",
        "shelfmark",
        "catalogue_numbers",
        "date",
    ],
    IndexType.GRAPHS: [
        "id",
        "item_image",
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
}

# Attributes that can be used for sort.
SORTABLE_ATTRIBUTES: dict[IndexType, list[str]] = {
    IndexType.ITEM_PARTS: [
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
    IndexType.ITEM_IMAGES: [
        "id",
        "repository_name",
        "repository_city",
        "shelfmark",
        "type",
        "number_of_annotations",
    ],
    IndexType.SCRIBES: ["id", "name", "scriptorium"],
    IndexType.HANDS: [
        "id",
        "name",
        "repository_name",
        "repository_city",
        "shelfmark",
        "place",
        "catalogue_numbers",
    ],
    IndexType.GRAPHS: [
        "id",
        "repository_name",
        "repository_city",
        "shelfmark",
        "allograph",
    ],
}

# Default facet attributes per index (for facets endpoint when facets param omitted).
DEFAULT_FACET_ATTRIBUTES: dict[IndexType, list[str]] = {
    IndexType.ITEM_PARTS: [
        "image_availability",
        "type",
        "repository_city",
        "repository_name",
        "format",
        "date_min",
        "date_max",
    ],
    IndexType.ITEM_IMAGES: ["locus", "type", "repository_city", "repository_name", "components", "features", "component_features"],
    IndexType.SCRIBES: ["scriptorium"],
    IndexType.HANDS: ["repository_city", "repository_name", "place"],
    IndexType.GRAPHS: [
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
}

# Attributes used for full-text search (q). Can be minimal.
SEARCHABLE_ATTRIBUTES: dict[IndexType, list[str]] = {
    IndexType.ITEM_PARTS: ["repository_name", "repository_city", "shelfmark", "catalogue_numbers", "type"],
    IndexType.ITEM_IMAGES: ["locus", "repository_name", "shelfmark", "components", "features"],
    IndexType.SCRIBES: ["name", "scriptorium"],
    IndexType.HANDS: ["name", "place", "description", "repository_name", "shelfmark"],
    IndexType.GRAPHS: ["repository_name", "shelfmark", "allograph", "character", "hand_name", "components"],
}
