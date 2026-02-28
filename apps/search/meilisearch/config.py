"""Meilisearch index settings per IndexType. Derived from search registry."""

from apps.search.registry import INDEX_REGISTRY

FILTERABLE_ATTRIBUTES = {
    index_type: registration.filterable_attributes for index_type, registration in INDEX_REGISTRY.items()
}

SORTABLE_ATTRIBUTES = {
    index_type: registration.sortable_attributes for index_type, registration in INDEX_REGISTRY.items()
}

DEFAULT_FACET_ATTRIBUTES = {
    index_type: registration.default_facet_attributes for index_type, registration in INDEX_REGISTRY.items()
}

SEARCHABLE_ATTRIBUTES = {
    index_type: registration.searchable_attributes for index_type, registration in INDEX_REGISTRY.items()
}
