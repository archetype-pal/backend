"""Use case: ReindexIndex. Load documents from DB, write to index."""

from django.apps import apps

from apps.search.domain import IndexType
from apps.search.infrastructure.document_builders import BUILDERS
from apps.search.infrastructure.meilisearch_writer import MeilisearchIndexWriter


def get_queryset_for_index(index_type: IndexType):
    """Return the Django model queryset for the given index type."""
    model_map = {
        IndexType.ITEM_PARTS: ("manuscripts", "ItemPart"),
        IndexType.ITEM_IMAGES: ("manuscripts", "ItemImage"),
        IndexType.SCRIBES: ("scribes", "Scribe"),
        IndexType.HANDS: ("scribes", "Hand"),
        IndexType.GRAPHS: ("annotations", "Graph"),
    }
    app_label, model_name = model_map[index_type]
    model = apps.get_model(app_label, model_name)
    return model.objects.all().order_by("pk")


class ReindexIndex:
    """Reindex: load documents from DB via document builders, replace index. Depends on IIndexWriter."""

    def __init__(self, writer: MeilisearchIndexWriter | None = None):
        self._writer = writer or MeilisearchIndexWriter()

    def __call__(self, index_type: IndexType) -> int:
        """Load all documents for index_type from DB, replace index. Returns count of documents indexed."""
        builder = BUILDERS.get(index_type)
        if not builder:
            raise ValueError(f"No document builder for index type {index_type}")

        qs = get_queryset_for_index(index_type)
        documents = []
        for obj in qs.iterator():
            doc = builder(obj)
            documents.append(doc)

        self._writer.replace_documents(index_type, documents)
        return len(documents)
