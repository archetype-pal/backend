"""The session status groups, and the copy of one the database keeps."""

from apps.uploads.models import ImageUploadSession

Status = ImageUploadSession.Status


def test_every_status_is_the_clients_the_workers_or_terminal():
    owned = [*ImageUploadSession.CLIENT_STATUSES, *ImageUploadSession.WORKER_STATUSES]
    assert len(owned) == len(set(owned))
    assert set(Status) - set(owned) == {Status.COMPLETE, Status.FAILED}


def test_the_unique_constraint_covers_exactly_the_active_statuses():
    """A migration cannot follow the tuple, so the constraint keeps its own list; it must not drift."""
    (constraint,) = (
        c for c in ImageUploadSession._meta.constraints if c.name == "uploads_one_active_session_per_destination"
    )
    ((lookup, statuses),) = constraint.condition.children
    assert lookup == "status__in"
    assert set(statuses) == set(ImageUploadSession.ACTIVE_STATUSES)
