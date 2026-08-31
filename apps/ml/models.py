"""The inference ledger — one row per AI inference, append-only and machine-written.

Its job is to answer, years later, *which model produced this record* — so it
records the model and its version, the hashed prompt, a content-addressed
reference to the inputs, the cost, and the canonical records the call touched.
That is the whole point of building it before the first model runs: the
provenance of an inference cannot be reconstructed after the fact.

Deliberately **not** audited via `apps.common.audit`. That log records what
humans did to research data; this table *is* the log for what models did, and
registering it would produce an `EditEvent` for every inference.
"""

from django.conf import settings
from django.db import models


class MLJob(models.Model):
    """One inference: what ran, on what, at what cost, and how it ended."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        # Declined by the budget guard or the kill switch, before any provider
        # was called. A refused row still costs nothing and still gets logged —
        # the ledger has to show the refusals or the spend caps are unauditable.
        REFUSED = "refused", "Refused"

    # The purpose of the call — a programme item ("W1.1"), or a named routine.
    # Free text rather than choices: the ledger must accept work from items that
    # do not exist yet without a migration.
    task = models.CharField(max_length=64, db_index=True)
    provider = models.CharField(max_length=64)
    # Hosted model identifiers are long and versioned; size generously.
    model_name = models.CharField(max_length=128, blank=True, default="")
    model_version = models.CharField(max_length=128, blank=True, default="")
    # sha256 hex digests. The prompt itself is not stored: it can contain corpus
    # text, and the hash is what reproducibility actually needs.
    prompt_hash = models.CharField(max_length=64, blank=True, default="")
    input_ref = models.CharField(max_length=64, blank=True, default="", db_index=True)
    params = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    # Integer millionths of a currency unit, never a float: the budget guard
    # sums this column and money must not drift.
    cost_micros = models.BigIntegerField(default=0)
    cost_currency = models.CharField(max_length=3, blank=True, default="")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ml_jobs",
    )
    celery_task_id = models.CharField(max_length=64, blank=True, default="")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]
        verbose_name = "ML job"
        verbose_name_plural = "ML jobs"
        indexes = [
            models.Index(fields=["task", "-created"], name="mljob_task_created_idx"),
            models.Index(fields=["status", "-created"], name="mljob_status_created_idx"),
            models.Index(fields=["actor", "-created"], name="mljob_actor_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.task} · {self.model_name or self.provider} · {self.status}"


class MLJobTarget(models.Model):
    """A canonical record an inference produced or modified.

    Loose `(target_type, target_id)` pointers rather than foreign keys, for the
    same reason `common.EditEvent` uses them — and one more. A provenance log
    has to outlive what it describes: an FK would cascade or block when the
    record is deleted, and the one question this table exists to answer
    ("what produced this?") is still worth answering about a row that is gone.

    It also keeps `apps.ml` importing nothing but `apps.common`, which is how
    the architecture invariant — no edge from the inference service to the
    canonical record — ends up enforced by `check_architecture_boundaries.py`
    rather than by prose.
    """

    job = models.ForeignKey(MLJob, on_delete=models.CASCADE, related_name="targets")
    target_type = models.CharField(max_length=64)
    target_id = models.BigIntegerField()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "target_type", "target_id"],
                name="unique_ml_job_target",
            )
        ]
        indexes = [models.Index(fields=["target_type", "target_id"], name="mljobtarget_target_idx")]

    def __str__(self) -> str:
        return f"{self.target_type}#{self.target_id}"


class EvaluationRun(models.Model):
    """One held-out evaluation of one model version (W0.3).

    The programme's release rule is that no model reaches users without
    published numbers, and no number ships without its split and its baseline.
    That rule lives in this table's shape: `release`, `split`, `baseline_name`
    and `baseline_metrics` are not optional, and
    `apps.ml.services.evaluation.record_run` refuses to write a row missing any
    of them. A score with no floor beside it is not a result, and a score whose
    split nobody recorded cannot be reproduced.
    """

    model_name = models.CharField(max_length=128)
    model_version = models.CharField(max_length=128, blank=True, default="")
    task = models.CharField(max_length=64, db_index=True)

    # Which frozen release, and which of its splits. Evaluation never runs
    # against the live corpus — a number computed on moving data cannot be
    # re-derived, which is what W0.2 froze the splits for.
    release = models.CharField(max_length=64)
    split = models.CharField(max_length=32)

    metrics = models.JSONField()
    baseline_name = models.CharField(max_length=64)
    baseline_metrics = models.JSONField()
    notes = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]
        indexes = [models.Index(fields=["task", "-created"], name="evalrun_task_created_idx")]

    def __str__(self) -> str:
        return f"{self.model_name}@{self.model_version or '?'} · {self.task} · {self.release}/{self.split}"

    @property
    def headline(self) -> float:
        return float(self.metrics.get("accuracy", 0.0))

    @property
    def baseline_headline(self) -> float:
        return float(self.baseline_metrics.get("accuracy", 0.0))

    @property
    def beats_baseline(self) -> bool:
        """Whether the model cleared its floor. Reported, never assumed."""
        return self.headline > self.baseline_headline
