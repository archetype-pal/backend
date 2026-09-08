"""Scoped service identities, and a log of everything an agent was asked.

§8.5 is blunt about why this app exists: *"No existing permission concept
expresses a per-agent service identity with an explicit tool allow-list.
Building one is a prerequisite of Phase 3."* Backoffice access today is
all-or-nothing, so without this an agent would carry the highest-privilege
credential in the system and be restrained only by its prompt.

The rule this encodes: **least privilege is enforced by the credential, not the
prompt.** A tool the identity has not been granted is not described to the
model, is not offered to it, and is refused if it asks anyway. All three,
because a model that never hears about a tool can still guess its name.
"""

from django.conf import settings
from django.db import models


class ServiceIdentity(models.Model):
    """One agent's credential: what it may call, and how often.

    Deliberately not a `User`. A `User` carries `is_staff`/`is_superuser` and a
    password, and every permission in the platform is written against those —
    so an agent that were one would be inside the human authorisation model
    rather than beside it, one flag away from the backoffice.
    """

    slug = models.SlugField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    # The allow-list. Names must resolve in `apps.agents.tools.TOOL_REGISTRY`;
    # an unknown name grants nothing rather than everything.
    allowed_tools = models.JSONField(default=list)
    # Per-identity quota over a rolling day. §8.5: the platform's anonymous rate
    # limit is not a quota, and "rate-limited, logged" is not a posture.
    daily_run_quota = models.PositiveIntegerField(default=200)
    max_turns = models.PositiveSmallIntegerField(default=8, help_text="Tool-calling turns before the loop is cut off.")
    model_name = models.CharField(
        max_length=128, blank=True, default="", help_text="Provider model slug; blank uses the default."
    )
    enabled = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Service identities"
        ordering = ["slug"]

    def __str__(self) -> str:
        return str(self.slug)

    def may_call(self, tool_name: str) -> bool:
        return tool_name in set(self.allowed_tools or [])


class AgentRun(models.Model):
    """One question and what the agent did with it.

    Logged in full, unlike the inference ledger — which stores a digest and no
    text, because its inputs are corpus material the data policy governs. A
    question typed into a public box is not that: it is the user's own words,
    and it is the only record of what the agent was asked to do. Keeping it is
    how an injection attempt is found after the fact.
    """

    class Status(models.TextChoices):
        ANSWERED = "answered", "Answered"
        REFUSED = "refused", "Refused"
        FAILED = "failed", "Failed"
        EXHAUSTED = "exhausted", "Turn limit reached"

    identity = models.ForeignKey(ServiceIdentity, related_name="runs", on_delete=models.PROTECT)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_runs"
    )
    # A coarse per-requester key for anonymous quota accounting. Not an address:
    # storing raw client IPs against every question asked of a public research
    # tool is more personal data than the quota needs.
    requester_key = models.CharField(max_length=64, blank=True, default="", db_index=True)

    question = models.TextField()
    answer = models.TextField(blank=True, default="")
    # Every anchor the answer cites, after each was resolved against a real
    # record. §8.3 is the difference between a clickable anchor and a correct
    # one, so unresolvable citations never reach here.
    citations = models.JSONField(default=list)
    tool_calls = models.JSONField(default=list)
    turns = models.PositiveSmallIntegerField(default=0)

    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    error = models.TextField(blank=True, default="")
    cost_micros = models.BigIntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]
        indexes = [models.Index(fields=["identity", "created"], name="agentrun_identity_created_idx")]

    def __str__(self) -> str:
        return f"{self.identity_id}: {self.question[:60]}"
