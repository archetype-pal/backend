from django.conf import settings
from django.db import models


class Date(models.Model):
    date = models.CharField(max_length=100)
    # Use the following two fields to represent the date as a numeric value
    #   This way, it can be used for sorting.
    min_weight = models.IntegerField(verbose_name="Minimum weight", help_text="The lower bound of the date range")
    max_weight = models.IntegerField(verbose_name="Maximum weight", help_text="The upper bound of the date range")

    def __str__(self):
        return self.date

    class Meta:
        verbose_name = "Date"
        ordering = ["date"]


class EditEvent(models.Model):
    """Append-only audit log for editor changes (M5.2).

    The viewer / editor surfaces show "X changed Y at Z"; review workflows
    surface "what changed since last week". The log is decoupled from any one
    domain table so we can track ImageText / Graph / etc. behind a single tab.
    """

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"
        STATUS_CHANGED = "status_changed", "Status changed"
        COMMENTED = "commented", "Commented"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="edit_events",
    )
    action = models.CharField(max_length=24, choices=Action.choices)
    target_type = models.CharField(max_length=64, db_index=True)  # "graph", "imagetext", …
    target_id = models.BigIntegerField(db_index=True)
    summary = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="editevent_target_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}#{self.target_id} by {self.actor_id} @ {self.created}"
