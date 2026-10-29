"""Progress reporting for search-index rebuilds.

Rebuilds progress on two axes: an outer loop moving between index types and an
inner loop streaming document batches. Service code signals both through
`advance_to` (outer) and `report_batch` (inner); where that goes (a Celery
state, nowhere) is the reporter's business.
"""

from celery.app.task import Task


class ProgressReporter:
    """Base reporter: every hook is a no-op, for management commands, tests and ad-hoc reindexes."""

    def start(self, message: str) -> None:
        pass

    def advance_to(self, index_position: int, total_indexes: int, segment: str) -> None:
        pass

    def report_batch(self, done: int, total: int) -> None:
        """Documents written for the segment named by the last `advance_to`."""


class CeleryTaskReporter(ProgressReporter):
    """Reports progress by calling `task.update_state` on a bound Celery task.

    The current index segment, position and total live on the reporter so
    `IndexingService` only passes `report_batch(done, total)`. `reindex_all`
    calls `advance_to(...)` when it moves between indexes; a single-index
    reindex calls `advance_to(1, 1, segment)` once after `start(...)`.
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
