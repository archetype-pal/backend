"""Celery tasks for vision. Thin: each hands an id to the service."""

from celery import shared_task

from apps.vision.services import page_drafts, page_letters


@shared_task(soft_time_limit=page_drafts.TIME_LIMIT, time_limit=page_drafts.TIME_LIMIT + 60)
def draft_page(draft_id: int) -> dict[str, int | str]:
    draft = page_drafts.draft_page(draft_id)
    return {"action": "page_draft", "draft": draft.pk, "status": draft.status}


@shared_task(soft_time_limit=page_letters.TIME_LIMIT, time_limit=page_letters.TIME_LIMIT + 60)
def propose_page_letters(run_id: int) -> dict[str, int | str]:
    run = page_letters.propose(run_id)
    return {"action": "page_letters", "run": run.pk, "status": run.status, "proposed": run.proposed}
