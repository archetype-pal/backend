"""The copy of the active session statuses the database keeps."""

from apps.uploads.models import ImageUploadSession


def test_the_unique_constraint_covers_exactly_the_active_statuses():
    """A migration cannot follow the tuple, so the constraint keeps its own list; it must not drift."""
    (constraint,) = (
        c for c in ImageUploadSession._meta.constraints if c.name == "uploads_one_active_session_per_destination"
    )
    ((lookup, statuses),) = constraint.condition.children
    assert lookup == "status__in"
    assert set(statuses) == set(ImageUploadSession.ACTIVE_STATUSES)
