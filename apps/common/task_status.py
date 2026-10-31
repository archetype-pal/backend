"""Reading a Celery task's state for the task-polling endpoints (search management, uploads)."""

from typing import Any

from celery.result import AsyncResult


def task_status(task_id: str) -> dict[str, Any]:
    """`{task_id, state, progress, result, error}` as the frontend polls it.

    `progress` is whatever the task put in `update_state(meta=...)`. Reading
    the result backend can itself fail; that is reported as a FAILURE rather
    than raised, so a polling request never 500s.
    """
    info: dict[str, Any] = {"task_id": task_id, "state": "FAILURE", "progress": None, "result": None, "error": None}
    try:
        result: AsyncResult[Any] = AsyncResult(task_id)
        state: str = result.state
        info["state"] = state
        if state in ("PROGRESS", "STARTED") and result.info:
            info["progress"] = result.info
        elif state == "SUCCESS":
            res, _ = _safe_task_result(result)
            if res is not None:
                info["result"] = res
        elif state == "FAILURE":
            _, err = _safe_task_result(result)
            info["error"] = err or "Task failed."
    except Exception as exc:
        info["state"] = "FAILURE"
        info["error"] = str(exc) or "Failed to retrieve task status."
    return info


def _format_task_error(result: Any) -> str:
    if result is None:
        return "Unknown error"
    if isinstance(result, BaseException):
        return str(result) or type(result).__name__
    if isinstance(result, dict):
        msg: Any = result.get("exc_message") or result.get("message") or result.get("error")
        if isinstance(msg, (list, tuple)):
            msg = " ".join(str(item) for item in msg)
        exc_type: str = result.get("exc_type", "")
        if msg and exc_type:
            return f"{exc_type}: {msg}"
        return str(msg) if msg else str(result)
    return str(result)


def _safe_task_result(result: AsyncResult[Any]) -> tuple[Any | None, str | None]:
    if not result.ready():
        return (None, None)
    try:
        raw: Any = result.get(propagate=False)
        if result.successful():
            return (raw, None)
        return (None, _format_task_error(raw))
    except Exception as exc:
        return (None, str(exc) or "Could not retrieve task result.")
