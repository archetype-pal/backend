"""Progress reporting for search-index rebuilds.

The indexing pipeline has two layers of progress:

  1. The outer multi-index loop ("clear and rebuild all") advancing between
     index types — item-parts → scribes → texts → …
  2. The inner per-index loop streaming document batches into Meilisearch —
     500 docs at a time.

Before this module, each layer wrapped the next layer's callback in a
closure that had to re-shape the signature ((done, total) →
(pos, total_indexes, segment, done, total_docs) → Celery `update_state`).
That made the call graph hard to follow and turned every test into a
mocked-callback puzzle.

The `ProgressReporter` protocol below replaces those callbacks with a
stable, typed contract. Service code calls `reporter.advance_to(...)`
when the outer loop moves and `reporter.report_batch(done, total)` from
inside the per-index loop; the *sink* (Celery task, log line, no-op) is
the reporter's concern alone. Layers below no longer need to know how
progress is delivered.
"""

from typing import Protocol

from celery.app.task import Task


class ProgressReporter(Protocol):
    """Receives progress signals from indexing services."""

    def start(self, message: str) -> None:
        """Signal that a top-level operation has begun (Celery STARTED)."""
        ...

    def advance_to(self, index_position: int, total_indexes: int, segment: str) -> None:
        """Signal the outer multi-index loop is moving to *segment*."""
        ...

    def report_batch(self, done: int, total: int) -> None:
        """Signal that *done* of *total* documents have been written for the
        current index segment."""
        ...


class NoopReporter:
    """Default reporter used when callers don't care about progress
    (management commands, tests, ad-hoc reindexes)."""

    def start(self, message: str) -> None:
        del message

    def advance_to(self, index_position: int, total_indexes: int, segment: str) -> None:
        del index_position, total_indexes, segment

    def report_batch(self, done: int, total: int) -> None:
        del done, total


class CeleryTaskReporter:
    """Reports progress by calling `task.update_state` on a bound Celery task.

    Mutable state (current index segment, position, total) lives on the
    reporter so `IndexingService` and `SearchOrchestrationService` don't have
    to pass it down — `report_batch(done, total)` is enough. The orchestrator
    calls `advance_to(...)` once when it moves between indexes; the reporter
    remembers where it is and decorates subsequent batch reports.

    For single-index reindex tasks, callers should call
    `advance_to(1, 1, segment)` once after `start(...)` so batch reports
    carry the right segment label.
    """

    def __init__(self, task: Task) -> None:
        self._task = task
        self._index_position = 1
        self._total_indexes = 1
        self._segment = ""

    def start(self, message: str) -> None:
        self._task.update_state(
            state="STARTED",
            meta={
                "current": 0,
                "total": self._total_indexes,
                "message": message,
                "index_done": 0,
                "index_total": 0,
            },
        )

    def advance_to(self, index_position: int, total_indexes: int, segment: str) -> None:
        self._index_position = index_position
        self._total_indexes = total_indexes
        self._segment = segment

    def report_batch(self, done: int, total: int) -> None:
        self._task.update_state(
            state="PROGRESS",
            meta={
                "current": self._index_position,
                "total": self._total_indexes,
                "message": f"Reindexing {self._segment}… {done}/{total} docs",
                "index_done": done,
                "index_total": total,
            },
        )
