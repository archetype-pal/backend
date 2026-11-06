from unittest import mock

from apps.common.task_status import task_status


def test_an_unreachable_result_backend_is_a_failure_not_a_500():
    with mock.patch("apps.common.task_status.AsyncResult") as async_result:
        type(async_result.return_value).state = mock.PropertyMock(side_effect=ConnectionError("redis down"))

        info = task_status("task-1")

    assert info["state"] == "FAILURE"
    assert info["error"] == "redis down"
    assert info["task_id"] == "task-1"


def test_a_running_task_reports_its_progress():
    with mock.patch("apps.common.task_status.AsyncResult") as async_result:
        result = async_result.return_value
        result.state = "PROGRESS"
        result.info = {"current": 2, "total": 9}

        info = task_status("task-1")

    assert info == {
        "task_id": "task-1",
        "state": "PROGRESS",
        "progress": {"current": 2, "total": 9},
        "result": None,
        "error": None,
    }
