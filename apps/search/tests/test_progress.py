"""Unit tests for ProgressReporter implementations."""

from unittest.mock import MagicMock

from apps.search.progress import CeleryTaskReporter, NoopReporter


def test_noop_reporter_is_a_no_op():
    # Should accept the protocol calls without raising or returning anything.
    reporter = NoopReporter()
    assert reporter.start("anything") is None
    assert reporter.advance_to(1, 5, "item-parts") is None
    assert reporter.report_batch(100, 500) is None


def test_celery_task_reporter_start_emits_started_state():
    task = MagicMock()
    reporter = CeleryTaskReporter(task)

    reporter.start("Reindexing item-parts…")

    task.update_state.assert_called_once_with(
        state="STARTED",
        meta={
            "current": 0,
            "total": 1,
            "message": "Reindexing item-parts…",
            "index_done": 0,
            "index_total": 0,
        },
    )


def test_celery_task_reporter_report_batch_uses_last_advance_to_context():
    """Regression net for the bug the old closure-chain hid: batch reports
    must carry the segment label set by `advance_to`, not whatever the
    constructor defaulted to."""
    task = MagicMock()
    reporter = CeleryTaskReporter(task)

    reporter.advance_to(2, 6, "scribes")
    reporter.report_batch(50, 200)

    # advance_to itself does NOT emit — only report_batch / start do. This
    # keeps the Celery state stream tied to actual progress, not to
    # bookkeeping.
    task.update_state.assert_called_once_with(
        state="PROGRESS",
        meta={
            "current": 2,
            "total": 6,
            "message": "Reindexing scribes… 50/200 docs",
            "index_done": 50,
            "index_total": 200,
        },
    )


def test_celery_task_reporter_advance_to_does_not_emit_directly():
    task = MagicMock()
    reporter = CeleryTaskReporter(task)
    reporter.advance_to(1, 6, "item-parts")
    task.update_state.assert_not_called()


def test_celery_task_reporter_batches_after_each_advance_reflect_new_segment():
    task = MagicMock()
    reporter = CeleryTaskReporter(task)

    reporter.advance_to(1, 2, "item-parts")
    reporter.report_batch(500, 500)
    reporter.advance_to(2, 2, "scribes")
    reporter.report_batch(120, 300)

    assert task.update_state.call_count == 2
    first_meta = task.update_state.call_args_list[0].kwargs["meta"]
    second_meta = task.update_state.call_args_list[1].kwargs["meta"]
    assert first_meta["message"] == "Reindexing item-parts… 500/500 docs"
    assert first_meta["current"] == 1
    assert second_meta["message"] == "Reindexing scribes… 120/300 docs"
    assert second_meta["current"] == 2
