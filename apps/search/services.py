"""Application services: `SearchService` reads, `IndexingService` writes."""

from collections.abc import Sequence
from contextlib import contextmanager
from itertools import islice
import logging
import time

from django.core.cache import caches
from django.db import close_old_connections
from meilisearch.errors import MeilisearchApiError

from apps.search.contracts import SearchBackend, SearchDocument
from apps.search.meilisearch.reader import HIGHLIGHT_PRE_TAG, MeilisearchIndexReader
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.progress import ProgressReporter
from apps.search.registry import get_queryset_for_index, get_registration
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

logger = logging.getLogger(__name__)

REINDEX_LOCK_EXPIRY_SECONDS = 60 * 60
NO_FACETS = FacetResult(facet_distribution={}, facet_stats={})


class ReindexInProgressError(RuntimeError):
    """Raised when a reindex for the same index is already running."""


@contextmanager
def reindex_lock(index_type: IndexType):
    """Stops two concurrent rebuilds clobbering the shared ``__build`` index.

    Backed by the Redis ``locks`` cache, and degrades to a no-op when that is
    unavailable: protection is best-effort, never a hard dependency. The lock
    expires after an hour or three times the previous rebuild of the same
    index, whichever is longer, so a large corpus cannot outlive its own lock.
    """
    key = f"search:reindex:{index_type}"
    duration_key = f"{key}:last_duration"
    try:
        cache = caches["locks"]
        expiry = max(REINDEX_LOCK_EXPIRY_SECONDS, 3 * int(cache.get(duration_key) or 0))
        acquired = cache.add(key, "1", expiry)
    except Exception as exc:
        logger.warning("Reindex lock backend unavailable (%s); proceeding without lock for %s.", exc, index_type)
        yield
        return
    if not acquired:
        raise ReindexInProgressError(f"A reindex for '{index_type}' is already running.")
    started = time.monotonic()
    try:
        yield
    finally:
        # Release first: the duration is only a hint for the next expiry, and a
        # failure writing it must not leave the lock held until it times out.
        try:
            cache.delete(key)
        except Exception:
            logger.warning("Failed to release reindex lock for %s.", index_type)
        try:
            cache.set(duration_key, int(time.monotonic() - started), None)
        except Exception:
            logger.warning("Failed to record reindex duration for %s.", index_type)


SUGGEST_SNIPPET_CROP_WORDS = 24
SUGGEST_LABEL_FIELDS = ("display_label", "shelfmark", "name", "allograph", "locus")


def _indexes_full_text(index_type: IndexType) -> bool:
    return "content" in get_registration(index_type).searchable_attributes


def _hit_label(hit: dict) -> str:
    """The first label field with text in it; a blank or whitespace-only field falls through to the next."""
    labels = (str(hit.get(field) or "").strip() for field in SUGGEST_LABEL_FIELDS)
    return next((label for label in labels if label), "")


def _highlighted_snippet(hit: dict) -> str | None:
    formatted = hit.get("_formatted")
    snippet = formatted.get("content") if isinstance(formatted, dict) else None
    return snippet if isinstance(snippet, str) and HIGHLIGHT_PRE_TAG in snippet else None


class SearchService:
    def __init__(self, reader: SearchBackend | None = None):
        self._reader = reader or MeilisearchIndexReader()

    def search(self, index_type: IndexType, query: SearchQuery) -> SearchResult:
        result, _ = self._reader.search(index_type, query, facet_attributes=None)
        return result

    def search_with_facets(
        self, index_type: IndexType, query: SearchQuery, facet_attributes: list[str]
    ) -> tuple[SearchResult, FacetResult]:
        """One round-trip for hits and facet counts.

        Facets are declared in registry.py, so between deploying a new one and
        running setup-search-indexes Meilisearch rejects the whole search.
        Degrading to "no facets" (and a plain search) keeps results rendering.
        """
        try:
            result, facets = self._reader.search(index_type, query, facet_attributes=facet_attributes)
        except MeilisearchApiError as exc:
            if getattr(exc, "code", None) != "invalid_search_facets":
                raise
            logger.warning(
                "Meilisearch rejected facet attributes %s on %s (index settings out of date — "
                "run setup-search-indexes): %s",
                facet_attributes,
                index_type,
                exc,
            )
            return self.search(index_type, query), NO_FACETS
        return result, facets or NO_FACETS

    def get_document(self, index_type: IndexType, doc_id: int | str) -> dict | None:
        return self._reader.get_document_by_id(index_type, doc_id)

    def suggest(
        self,
        index_types: list[IndexType],
        query_text: str,
        *,
        per_type_limit: int = 5,
    ) -> dict[str, list[dict[str, str | int | float]]]:
        """Type-ahead labels per index segment, with a highlighted content snippet on full-text indexes."""
        normalized_q = query_text.strip()
        if not normalized_q:
            return {}

        specs: list[tuple[IndexType, SearchQuery]] = []
        for index_type in index_types:
            full_text = _indexes_full_text(index_type)
            specs.append(
                (
                    index_type,
                    SearchQuery(
                        q=normalized_q,
                        limit=per_type_limit,
                        attributes_to_retrieve=["id", *SUGGEST_LABEL_FIELDS, *(["content"] if full_text else [])],
                        attributes_to_crop=["content"] if full_text else [],
                        crop_length=SUGGEST_SNIPPET_CROP_WORDS if full_text else None,
                    ),
                )
            )

        suggestions: dict[str, list[dict[str, str | int | float]]] = {}
        for index_type, result in self._reader.multi_search(specs):
            full_text = _indexes_full_text(index_type)
            items: dict[str, dict[str, str | int | float]] = {}  # by label, so duplicates collapse
            for hit in result.hits:
                label = _hit_label(hit) if isinstance(hit, dict) else ""
                if not label or label in items:
                    continue
                items[label] = {"id": str(hit.get("id", label)), "label": label}
                if full_text and (snippet := _highlighted_snippet(hit)):
                    items[label]["snippet"] = snippet
                if len(items) >= per_type_limit:
                    break
            suggestions[index_type.segment] = list(items.values())
        return suggestions


class IndexingService:
    REINDEX_BATCH_SIZE = 500

    def __init__(self, writer: MeilisearchIndexWriter | None = None):
        self._writer = writer or MeilisearchIndexWriter()

    def reindex(self, index_type: IndexType, *, reporter: ProgressReporter | None = None) -> int:
        """Rebuild the index from the DB, returning the number of rows indexed.

        Documents go into a staging index and are swapped in with one Meilisearch
        operation, so a crash mid-rebuild leaves the live index stale but whole.
        The next run drops the orphaned staging index. There is deliberately no
        "clear first" variant: clearing would only open a zero-results window.

        Reports per-batch progress via `reporter.report_batch(done, total)`.
        """
        reporter = reporter or ProgressReporter()
        registration = get_registration(index_type)
        queryset = get_queryset_for_index(index_type)
        total = queryset.count()

        with reindex_lock(index_type):
            self._writer.ensure_index_and_settings(index_type)
            self._writer.prepare_build_index(index_type)

            processed = 0
            rows = queryset.iterator(chunk_size=self.REINDEX_BATCH_SIZE)
            while batch := list(islice(rows, self.REINDEX_BATCH_SIZE)):
                close_old_connections()
                documents: list[SearchDocument] = []
                for obj in batch:
                    documents.extend(registration.documents(obj))
                self._writer.add_documents_to_build(index_type, documents)
                processed += len(batch)
                reporter.report_batch(processed, total)

            self._writer.swap_with_build(index_type)
            self._writer.drop_build_index(index_type)

        return processed

    def reindex_all(self, *, reporter: ProgressReporter | None = None) -> dict[str, int]:
        """Rebuild every index in turn, keyed by segment; one failing index is logged and skipped."""
        reporter = reporter or ProgressReporter()
        indexed: dict[str, int] = {}
        for position, index_type in enumerate(IndexType, start=1):
            reporter.advance_to(position, len(IndexType), index_type.segment)
            try:
                indexed[index_type.segment] = self.reindex(index_type, reporter=reporter)
            except Exception:
                logger.exception("Reindex failed for %s; continuing with remaining indexes.", index_type.segment)
        return indexed

    def clear(self, index_type: IndexType) -> None:
        self._writer.delete_all(index_type)

    def update_documents_by_ids(self, index_type: IndexType, pks: Sequence[int]) -> int:
        """Rebuild the documents of these source rows in place; returns the number of documents written.

        A row the index's queryset no longer returns (trashed, hard-deleted, or
        excluded by the registration's filter) has its documents removed, so
        this one call covers add, update and remove.
        """
        if not pks:
            return 0

        registration = get_registration(index_type)
        found_pks: set[int] = set()
        documents: list[SearchDocument] = []
        for obj in get_queryset_for_index(index_type).filter(pk__in=pks):
            found_pks.add(obj.pk)
            documents.extend(registration.documents(obj))

        if registration.parent_id_field:
            # Ids here are derived from the row (`42_0`), so a stale document
            # cannot be addressed by pk: clear everything these rows produced
            # before rebuilding. Covers a row that shrank its document count
            # and a row the queryset no longer returns at all. Tasks on one
            # index run in order, so the rebuild below lands after this.
            #
            # Documents are built first on purpose. A builder raising after the
            # delete would leave them gone with nothing to put back, and the
            # task's retry policy only covers Meilisearch communication errors.
            ids = ", ".join(str(int(pk)) for pk in pks)
            self._writer.delete_documents_by_filter(index_type, f"{registration.parent_id_field} IN [{ids}]")

        if documents:
            self._writer.update_documents(index_type, documents)

        if not registration.parent_id_field and (missing := [pk for pk in pks if pk not in found_pks]):
            self._writer.delete_documents(index_type, missing)
        return len(documents)

    def delete_documents_by_ids(self, index_type: IndexType, pks: Sequence[int]) -> None:
        if pks:
            self._writer.delete_documents(index_type, pks)

    def setup_index(self, index_type: IndexType) -> None:
        self._writer.ensure_index_and_settings(index_type)

    def setup_all(self) -> list[str]:
        for index_type in IndexType:
            self.setup_index(index_type)
        return IndexType.segments()
