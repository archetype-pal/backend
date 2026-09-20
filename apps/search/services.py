"""Search and indexing services (Meilisearch)."""

from collections.abc import Sequence
from contextlib import contextmanager
from itertools import islice
import logging

from django.core.cache import caches
from django.db import close_old_connections
from meilisearch.errors import MeilisearchApiError

from apps.search.contracts import SearchBackend, SearchDocument
from apps.search.meilisearch.reader import HIGHLIGHT_PRE_TAG, MeilisearchIndexReader
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.progress import NoopReporter, ProgressReporter
from apps.search.registry import get_queryset_for_index, get_registration
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

logger = logging.getLogger(__name__)

VALID_PER_INDEX_ACTIONS = {"reindex", "clear", "clean_and_reindex"}

REINDEX_LOCK_EXPIRY_SECONDS = 60 * 60


class ReindexInProgressError(RuntimeError):
    """Raised when a reindex for the same index is already running."""


@contextmanager
def reindex_lock(index_type: IndexType):
    """Cross-process single-flight lock for one index's atomic rebuild.

    Guards the ``prepare_build_index → swap_with_build`` critical section so two
    concurrent reindex runs (e.g. an operator double-click, or ``reindex_all``
    racing a single-index run) can't clobber the shared ``__build`` index.

    Backed by the Redis ``locks`` cache. If that backend is unavailable (e.g.
    host tests without Redis) the lock degrades to a no-op rather than blocking
    indexing — protection is best-effort, never a hard dependency.
    """
    key = f"search:reindex:{index_type.uid}"
    try:
        cache = caches["locks"]
        acquired = cache.add(key, "1", REINDEX_LOCK_EXPIRY_SECONDS)
    except Exception as exc:
        logger.warning("Reindex lock backend unavailable (%s); proceeding without lock for %s.", exc, index_type.uid)
        yield
        return
    if not acquired:
        raise ReindexInProgressError(f"A reindex for '{index_type.uid}' is already running.")
    try:
        yield
    finally:
        try:
            cache.delete(key)
        except Exception:
            logger.warning("Failed to release reindex lock for %s.", index_type.uid)


SUGGEST_SNIPPET_CROP_WORDS = 24
HIGHLIGHT_START_TOKEN = HIGHLIGHT_PRE_TAG
SUGGEST_LABEL_FIELDS = ("display_label", "shelfmark", "name", "allograph", "locus")


def _indexes_full_text(index_type: IndexType) -> bool:
    return "content" in get_registration(index_type).searchable_attributes


def _hit_label(hit: dict) -> str:
    for field in SUGGEST_LABEL_FIELDS:
        value = str(hit.get(field) or "").strip()
        if value:
            return value
    return ""


def _highlighted_snippet(hit: dict) -> str | None:
    formatted = hit.get("_formatted")
    snippet = formatted.get("content") if isinstance(formatted, dict) else None
    if isinstance(snippet, str) and HIGHLIGHT_START_TOKEN in snippet:
        return snippet
    return None


def resolve_index_type_segment(index_type_segment: str) -> IndexType:
    """Resolve URL segment to IndexType and raise on invalid values."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: '{index_type_segment}'.")
    return index_type


def index_type_segments() -> list[str]:
    """Return stable CLI/API index choices."""
    return [index_type.to_url_segment() for index_type in IndexType]


class SearchService:
    """Meilisearch search operations."""

    def __init__(self, reader: SearchBackend | None = None):
        self._reader = reader or MeilisearchIndexReader()

    def search(self, index_type: IndexType, query: SearchQuery) -> SearchResult:
        result, _ = self._reader.search(index_type, query, facet_attributes=None)
        return result

    def get_document(self, index_type: IndexType, doc_id: int | str) -> dict | None:
        return self._reader.get_document_by_id(index_type, doc_id)

    def get_facets(
        self,
        index_type: IndexType,
        query: SearchQuery,
        facet_attributes: list[str],
    ) -> FacetResult:
        try:
            _, facets = self._reader.search(index_type, query, facet_attributes=facet_attributes)
        except MeilisearchApiError as exc:
            # Facets are declared in registry.py, so between deploying a new one
            # and running setup-search-indexes Meilisearch rejects the whole
            # search. Degrading to "no facets" keeps results rendering.
            if getattr(exc, "code", None) != "invalid_search_facets":
                raise
            logger.warning(
                "Meilisearch rejected facet attributes %s on %s (index settings out of date — "
                "run setup-search-indexes): %s",
                facet_attributes,
                index_type,
                exc,
            )
            return FacetResult(facet_distribution={}, facet_stats={})
        if facets is None:
            return FacetResult(facet_distribution={}, facet_stats={})
        return facets

    def suggest(
        self,
        index_types: list[IndexType],
        query_text: str,
        *,
        per_type_limit: int = 5,
    ) -> dict[str, list[dict[str, str | int | float]]]:
        suggestions: dict[str, list[dict[str, str | int | float]]] = {}
        normalized_q = query_text.strip()
        if not normalized_q:
            return suggestions

        specs: list[tuple[IndexType, SearchQuery]] = []
        for index_type in index_types:
            full_text = _indexes_full_text(index_type)
            specs.append(
                (
                    index_type,
                    SearchQuery(
                        q=normalized_q,
                        limit=per_type_limit,
                        offset=0,
                        attributes_to_retrieve=["id", *SUGGEST_LABEL_FIELDS, *(["content"] if full_text else [])],
                        attributes_to_crop=["content"] if full_text else [],
                        crop_length=SUGGEST_SNIPPET_CROP_WORDS if full_text else None,
                    ),
                )
            )

        for index_type, result in self._reader.multi_search(specs):
            full_text = _indexes_full_text(index_type)
            items: list[dict[str, str | int | float]] = []
            seen_labels: set[str] = set()
            for hit in result.hits:
                if not isinstance(hit, dict):
                    continue
                label = _hit_label(hit)
                if not label or label in seen_labels:
                    continue
                seen_labels.add(label)
                item: dict[str, str | int | float] = {
                    "id": str(hit.get("id", label)),
                    "label": label,
                }
                snippet = _highlighted_snippet(hit) if full_text else None
                if snippet:
                    item["snippet"] = snippet
                items.append(item)
                if len(items) >= per_type_limit:
                    break
            suggestions[index_type.to_url_segment()] = items
        return suggestions


class IndexingService:
    """Meilisearch indexing operations."""

    def __init__(self, writer: MeilisearchIndexWriter | None = None):
        self._writer = writer or MeilisearchIndexWriter()

    REINDEX_BATCH_SIZE = 500

    def reindex(
        self,
        index_type: IndexType,
        *,
        reporter: ProgressReporter | None = None,
    ) -> int:
        """Atomically rebuild the index for index_type from DB. Returns count indexed.

        Builds documents into a staging index (`<uid>__build`), then swaps it with the
        live index in one Meilisearch operation. If reindex crashes mid-stream, the live
        index keeps serving stale-but-consistent data — never a half-empty index. The
        next reindex drops the orphaned build index and starts fresh (P1.3).

        Reports per-batch progress via `reporter.report_batch(done, total)`. Defaults
        to a no-op reporter when callers don't care about progress.
        """
        reporter = reporter or NoopReporter()
        builder = get_registration(index_type).builder

        qs = get_queryset_for_index(index_type)
        total = qs.count()

        with reindex_lock(index_type):
            self._writer.ensure_index_and_settings(index_type)
            self._writer.prepare_build_index(index_type)

            processed = 0
            it = qs.iterator(chunk_size=self.REINDEX_BATCH_SIZE)
            while True:
                batch = list(islice(it, self.REINDEX_BATCH_SIZE))
                if not batch:
                    break
                close_old_connections()
                documents: list[SearchDocument] = []
                for obj in batch:
                    documents.extend(builder(obj))
                self._writer.add_documents_to_build(index_type, documents)
                processed += len(batch)
                reporter.report_batch(processed, total)

            self._writer.swap_with_build(index_type)
            self._writer.drop_build_index(index_type)

        return processed

    def clear(self, index_type: IndexType) -> None:
        """Delete all documents in the index."""
        self._writer.delete_all(index_type)

    def update_documents_by_ids(self, index_type: IndexType, pks: Sequence[int]) -> int:
        """Fetch records by IDs using the index's optimized queryset, build documents,
        and update Meilisearch in-place. If any ID is missing (e.g. trashed or hard-deleted),
        it is removed from Meilisearch to keep the index clean. Returns count indexed.
        """
        if not pks:
            return 0

        registration = get_registration(index_type)
        builder = registration.builder
        queryset = get_queryset_for_index(index_type).filter(pk__in=pks)

        found_pks: set[int] = set()
        documents: list[SearchDocument] = []
        for obj in queryset:
            found_pks.add(obj.pk)
            documents.extend(builder(obj))

        if documents:
            self._writer.update_documents(index_type, documents)

        missing_pks = [pk for pk in pks if pk not in found_pks]
        if missing_pks:
            self._writer.delete_documents(index_type, missing_pks)

        return len(documents)

    def delete_documents_by_ids(self, index_type: IndexType, pks: Sequence[int]) -> None:
        """Delete specific documents from Meilisearch by primary key."""
        if not pks:
            return
        self._writer.delete_documents(index_type, pks)

    def setup_index(self, index_type: IndexType) -> None:
        """Ensure index and Meilisearch settings exist."""
        self._writer.ensure_index_and_settings(index_type)

    def get_stats(self, index_type: IndexType) -> dict:
        """Return index stats (e.g. number of documents)."""
        return self._writer.get_stats(index_type)


class SearchOrchestrationService:
    """Single place for per-index and all-index search operations."""

    def __init__(self, indexing_service: IndexingService | None = None):
        self._indexing_service = indexing_service or IndexingService()

    def clear_index(self, index_type_segment: str) -> None:
        index_type = resolve_index_type_segment(index_type_segment)
        self._indexing_service.clear(index_type)

    def reindex_index(
        self,
        index_type_segment: str,
        *,
        reporter: ProgressReporter | None = None,
    ) -> int:
        index_type = resolve_index_type_segment(index_type_segment)
        return self._indexing_service.reindex(index_type, reporter=reporter)

    def clear_and_reindex_index(
        self,
        index_type_segment: str,
        *,
        reporter: ProgressReporter | None = None,
    ) -> int:
        index_type = resolve_index_type_segment(index_type_segment)
        # Deliberately no pre-clear: reindex() swaps a staging index in
        # atomically, so clearing first would only open a zero-results window.
        return self._indexing_service.reindex(index_type, reporter=reporter)

    def reindex_all(self) -> dict[str, int]:
        indexed_per_segment: dict[str, int] = {}
        for index_type in IndexType:
            segment = index_type.to_url_segment()
            try:
                indexed_per_segment[segment] = self._indexing_service.reindex(index_type)
            except Exception:
                logger.exception("Reindex failed for %s; continuing with remaining indexes.", segment)
        return indexed_per_segment

    def setup_all_indexes(self) -> list[str]:
        segments: list[str] = []
        for index_type in IndexType:
            self._indexing_service.setup_index(index_type)
            segments.append(index_type.to_url_segment())
        return segments

    def clear_and_reindex_all(
        self,
        *,
        reporter: ProgressReporter | None = None,
    ) -> dict[str, int]:
        reporter = reporter or NoopReporter()
        indexed_per_segment: dict[str, int] = {}
        total_indexes = len(IndexType)
        for index_position, index_type in enumerate(IndexType, start=1):
            segment = index_type.to_url_segment()
            reporter.advance_to(index_position, total_indexes, segment)
            try:
                indexed_per_segment[segment] = self._indexing_service.reindex(index_type, reporter=reporter)
            except Exception:
                logger.exception("Reindex failed for %s; continuing with remaining indexes.", segment)
        return indexed_per_segment
