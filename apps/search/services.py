"""Search and indexing services (Meilisearch)."""

from contextlib import contextmanager
from itertools import islice
import logging

from django.core.cache import caches
from django.db import close_old_connections

from apps.search.contracts import SearchBackend, SearchDocument
from apps.search.meilisearch.reader import HIGHLIGHT_PRE_TAG, MeilisearchIndexReader
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.progress import NoopReporter, ProgressReporter
from apps.search.registry import get_queryset_for_index, get_registration
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

logger = logging.getLogger(__name__)

VALID_PER_INDEX_ACTIONS = {"reindex", "clear", "clean_and_reindex"}

# Safety expiry on the reindex lock so a worker that dies mid-rebuild can't
# wedge an index's reindex forever; a full corpus rebuild is well under this.
REINDEX_LOCK_TIMEOUT_SECONDS = 60 * 60


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
        acquired = cache.add(key, "1", REINDEX_LOCK_TIMEOUT_SECONDS)
    except Exception as exc:  # lock backend down — degrade, don't block reindex
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


# Words of context to keep around a match when building autocomplete KWIC
# snippets from a text-bearing index's `content` field.
SUGGEST_SNIPPET_CROP_LENGTH = 24
HIGHLIGHT_START_TOKEN = HIGHLIGHT_PRE_TAG


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
        _, facets = self._reader.search(index_type, query, facet_attributes=facet_attributes)
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

        # Build one query per index and run them in a single federated
        # round-trip (POST /multi-search) instead of N sequential searches.
        specs: list[tuple[IndexType, SearchQuery]] = []
        for index_type in index_types:
            # Text-bearing indexes (texts/clauses) hold the transcription in a
            # `content` field. For those, crop+highlight `content` so the
            # suggestion can show a KWIC line — the passage where the term occurs.
            has_content = "content" in get_registration(index_type).searchable_attributes
            attributes_to_retrieve = ["id", "display_label", "shelfmark", "name", "allograph", "locus"]
            if has_content:
                attributes_to_retrieve.append("content")
            specs.append(
                (
                    index_type,
                    SearchQuery(
                        q=normalized_q,
                        limit=per_type_limit,
                        offset=0,
                        attributes_to_retrieve=attributes_to_retrieve,
                        attributes_to_crop=["content"] if has_content else [],
                        crop_length=SUGGEST_SNIPPET_CROP_LENGTH if has_content else None,
                    ),
                )
            )

        for index_type, result in self._reader.multi_search(specs):
            has_content = "content" in get_registration(index_type).searchable_attributes
            items: list[dict[str, str | int | float]] = []
            seen_labels: set[str] = set()
            for hit in result.hits:
                if not isinstance(hit, dict):
                    continue
                raw_label = (
                    hit.get("display_label")
                    or hit.get("shelfmark")
                    or hit.get("name")
                    or hit.get("allograph")
                    or hit.get("locus")
                )
                label = str(raw_label or "").strip()
                if not label or label in seen_labels:
                    continue
                seen_labels.add(label)
                item: dict[str, str | int | float] = {
                    "id": str(hit.get("id", label)),
                    "label": label,
                }
                # Only attach a snippet when the term actually matched inside the
                # text (the cropped value carries highlight markers) — otherwise
                # a label-only match would show an arbitrary opening line.
                if has_content:
                    formatted = hit.get("_formatted")
                    snippet = formatted.get("content") if isinstance(formatted, dict) else None
                    if isinstance(snippet, str) and HIGHLIGHT_START_TOKEN in snippet:
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

        # Single-flight: serialize the build→swap so concurrent runs can't
        # clobber each other's shared `__build` staging index.
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
        # No pre-clear: reindex() already builds into a staging index and swaps
        # it in atomically, so the live index keeps serving until the new one is
        # ready. Emptying it first would guarantee a zero-results window (and a
        # permanently empty index if the rebuild crashed).
        return self._indexing_service.reindex(index_type, reporter=reporter)

    def reindex_all(self) -> dict[str, int]:
        indexed_per_segment: dict[str, int] = {}
        for index_type in IndexType:
            segment = index_type.to_url_segment()
            # Isolate failures: one index erroring (or already locked) must not
            # abort the rest of the batch. Failed segments are logged and
            # omitted from the result rather than aborting the whole run.
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
            # Tell the reporter where we are in the outer loop; the reporter
            # decorates subsequent `report_batch` calls with this context.
            reporter.advance_to(index_position, total_indexes, segment)
            # No pre-clear (atomic swap handles replacement) and per-index error
            # isolation so one failure doesn't abort the remaining indexes.
            try:
                indexed_per_segment[segment] = self._indexing_service.reindex(index_type, reporter=reporter)
            except Exception:
                logger.exception("Reindex failed for %s; continuing with remaining indexes.", segment)
        return indexed_per_segment
