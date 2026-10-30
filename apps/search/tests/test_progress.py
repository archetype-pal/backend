from unittest.mock import MagicMock

from apps.search.progress import CeleryTaskReporter


def test_start_emits_the_started_state():
    task = MagicMock()

    CeleryTaskReporter(task).start("Reindexing item-parts…")

    task.update_state.assert_called_once_with(
        state="STARTED",
        meta={"current": 0, "total": 1, "message": "Reindexing item-parts…", "index_done": 0, "index_total": 0},
    )


def test_batch_reports_carry_the_segment_set_by_the_last_advance_to():
    task = MagicMock()
    reporter = CeleryTaskReporter(task)

    reporter.advance_to(1, 2, "item-parts")
    task.update_state.assert_not_called()  # advance_to is bookkeeping only
    reporter.report_batch(500, 500)
    reporter.advance_to(2, 2, "scribes")
    reporter.report_batch(120, 300)

    metas = [call.kwargs["meta"] for call in task.update_state.call_args_list]
    assert [(m["current"], m["total"], m["message"], m["index_done"], m["index_total"]) for m in metas] == [
        (1, 2, "Reindexing item-parts… 500/500 docs", 500, 500),
        (2, 2, "Reindexing scribes… 120/300 docs", 120, 300),
    ]
