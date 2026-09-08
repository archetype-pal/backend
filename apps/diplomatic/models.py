"""What the AI programme extracts from charter texts, and the gate in front of it.

Diplomatic is the study of the form and formulae of legal documents — as
distinct from palaeography, the study of the script. Phase 2 of the AI
programme is diplomatic work, so its outputs live here rather than being
scattered across the apps that hold the source material.

**Everything a model produces arrives as a `Proposal`.** W0.5 built that gate
for annotations; this generalises it, because C1's guarantee is about the
canonical record as a whole and not about `Graph` in particular. A pipeline
writes proposals and nothing else; `accept()` is the only path to a canonical
row, and it requires a named human. The concrete tables below therefore contain
only what somebody approved.
"""

from django.conf import settings
from django.db import models


class Proposal(models.Model):
    """One machine-authored suggestion, awaiting a human decision.

    Generic on purpose. Five programme items (W2.1, W2.2, W2.4, W3.2, W3.3) all
    have the same shape — read some corpus material, ask a model, propose
    something — and giving each its own review workflow would be five chances to
    get the gate subtly wrong.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    # The pipeline that produced it, e.g. "W2.1". Free text so a new item does
    # not need a migration.
    pipeline = models.CharField(max_length=32, db_index=True)
    # What it is about, in `EditEvent`'s vocabulary — loose pointers rather than
    # a foreign key per source type.
    source_type = models.CharField(max_length=64)
    source_id = models.BigIntegerField()
    payload = models.JSONField()
    confidence = models.FloatField(null=True, blank=True)

    # PROTECT: a proposal must stay attributable to the inference that made it.
    ml_job = models.ForeignKey(
        "ml.MLJob", null=True, blank=True, on_delete=models.PROTECT, related_name="diplomatic_proposals"
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="diplomatic_proposals_reviewed",
    )
    reviewed = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["pipeline", "status"], name="proposal_pipeline_status_idx"),
            models.Index(fields=["source_type", "source_id"], name="proposal_source_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.pipeline} on {self.source_type}#{self.source_id} ({self.status})"


class CharterEntity(models.Model):
    """A person, place, date or transaction a human approved for a charter.

    The platform had no entity model, which is why W2.1 records that where
    extracted entities live was an open question. This is the answer: a flat
    table keyed to the text the entity was read from, with the role that the
    existing `<persName>`/`<placeName>` markup does not carry.
    """

    class Role(models.TextChoices):
        GRANTER = "granter", "Granter"
        BENEFICIARY = "beneficiary", "Beneficiary"
        WITNESS = "witness", "Witness"
        PLACE = "place", "Place"
        DATE = "date", "Date"
        TRANSACTION = "transaction", "Transaction type"

    image_text = models.ForeignKey(
        "manuscripts.ImageText", related_name="diplomatic_entities", on_delete=models.CASCADE
    )
    role = models.CharField(max_length=16, choices=Role.choices, db_index=True)
    # The surface form as it appears in the charter, kept verbatim: normalising
    # in place would lose the reading a scholar can check.
    name = models.CharField(max_length=255)
    normalised = models.CharField(max_length=255, blank=True, default="")
    note = models.TextField(blank=True, default="")
    proposal = models.ForeignKey(Proposal, null=True, blank=True, on_delete=models.SET_NULL, related_name="entities")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["image_text", "role", "name"]
        verbose_name_plural = "Charter entities"
        indexes = [models.Index(fields=["role", "name"], name="entity_role_name_idx")]

    def __str__(self) -> str:
        return f"{self.get_role_display()}: {self.name}"


class Formula(models.Model):
    """A recurring diplomatic formula — a cluster, not a single occurrence.

    MoA has already published a formulary typology, so this is machine-scale
    variation analysis measured against it rather than a discovery of it:
    `published_type` is where the correspondence to that typology is recorded,
    and a cluster that matches nothing published is the interesting case.
    """

    class Kind(models.TextChoices):
        SANCTIO = "sanctio", "Sanctio"
        CORROBORATIO = "corroboratio", "Corroboratio"
        DISPOSITIVE = "dispositive", "Dispositive verb"
        SALUTATION = "salutation", "Salutation"
        NOTIFICATION = "notification", "Notification"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    label = models.CharField(max_length=255)
    exemplar = models.TextField(help_text="A representative wording of this formula.")
    published_type = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="The type in MoA's published formulary typology, where this matches one.",
    )
    proposal = models.ForeignKey(Proposal, null=True, blank=True, on_delete=models.SET_NULL, related_name="formulae")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "label"]
        verbose_name_plural = "Formulae"

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.label}"


class FormulaOccurrence(models.Model):
    """One charter's use of a formula. The queryable layer W2.2 promises."""

    formula = models.ForeignKey(Formula, related_name="occurrences", on_delete=models.CASCADE)
    image_text = models.ForeignKey(
        "manuscripts.ImageText", related_name="formula_occurrences", on_delete=models.CASCADE
    )
    excerpt = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["formula", "image_text"]
        constraints = [models.UniqueConstraint(fields=["formula", "image_text"], name="unique_formula_occurrence")]

    def __str__(self) -> str:
        return f"{self.formula} in text {self.image_text_id}"


class Relation(models.Model):
    """A knowledge-graph triple a human approved (W3.3).

    Subject and object are recorded as text rather than foreign keys because
    what a charter names is a *reading* — "Walter son of Alan" — and resolving
    that to a database row is itself a scholarly judgement, not a lookup.
    """

    class Predicate(models.TextChoices):
        GRANTED_BY = "granted_by", "Granted by"
        WITNESSED_BY = "witnessed_by", "Witnessed by"
        WRITTEN_BY = "written_by", "Written by"
        BENEFICIARY_OF = "beneficiary_of", "Beneficiary of"
        LOCATED_AT = "located_at", "Located at"

    image_text = models.ForeignKey(
        "manuscripts.ImageText", related_name="diplomatic_relations", on_delete=models.CASCADE
    )
    subject = models.CharField(max_length=255)
    predicate = models.CharField(max_length=24, choices=Predicate.choices, db_index=True)
    object = models.CharField(max_length=255)
    proposal = models.ForeignKey(Proposal, null=True, blank=True, on_delete=models.SET_NULL, related_name="relations")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["image_text", "predicate", "subject"]
        indexes = [models.Index(fields=["predicate", "object"], name="relation_predicate_object_idx")]

    def __str__(self) -> str:
        return f"{self.subject} —{self.predicate}→ {self.object}"
