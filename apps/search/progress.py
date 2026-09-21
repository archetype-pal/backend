"""Progress reporting for search-index rebuilds.

Rebuilds progress on two axes: an outer loop moving between index types and an
inner loop streaming document batches. Service code signals both through this
protocol — `advance_to` for the outer, `report_batch` for the inner — and where
that goes (a Celery state, a log line, nowhere) is the reporter's business.
"""

from typing import Protocol

from celery.app.task import Task


class ProgressReporter(Protocol):
    def start(self, message: str) -> None: ...

    def advance_to(self, index_position: int, total_indexes: int, segment: str) -> None: ...

    def report_batch(self, done: int, total: int) -> None:
        """Documents written for the segment named by the last `advance_to`."""
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
