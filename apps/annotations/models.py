from django.conf import settings
from django.db import models

from apps.common.models import LiveObjectsManager, SoftDeleteModel


class GraphQuerySet(models.QuerySet):
    def visible_to(self, user) -> GraphQuerySet:
        """Public-visibility rule in one place: editorial annotations are for
        signed-in users only, so anonymous requests never see them."""
        if getattr(user, "is_authenticated", False):
            return self
        return self.exclude(annotation_type=self.model.AnnotationType.EDITORIAL)  # type: ignore[no-any-return]

    def undescribed(self) -> GraphQuerySet:
        """Image graphs with no feature recorded: the rows whose `Graph.is_described()` is false."""
        return self.filter(annotation_type=self.model.AnnotationType.IMAGE).exclude(  # type: ignore[no-any-return]
            graphcomponent__features__isnull=False
        )


class Graph(SoftDeleteModel):
    class AnnotationType(models.TextChoices):
        IMAGE = "image", "Image"
        TEXT = "text", "Text"
        EDITORIAL = "editorial", "Editorial"

    item_image = models.ForeignKey("manuscripts.ItemImage", related_name="graphs", on_delete=models.CASCADE)
    annotation = models.JSONField()  # rename this to location
    note = models.TextField(blank=True, default="")
    internal_note = models.TextField(blank=True, default="")
    # The paleographic FKs below are required for IMAGE-typed graphs (a glyph
    # instance with allograph + scribal hand) but null for EDITORIAL and TEXT
    # rows. TEXT graphs are just regions on the image referenced from
    # `ImageText.content` by a `corresp="#gid-N"` attribute on a TEI element.
    # PROTECT, not CASCADE: an Allograph is a reusable symbol-definition lookup
    # row edited in the backoffice taxonomy. Deleting one must never cascade-
    # delete the Graph annotations (the research data) that reference it — it
    # must be blocked. Mirrors the sibling `hand` FK below. (SET_NULL is not an
    # option: the `graph_editorial_or_required_allograph_hand` constraint
    # requires a non-null allograph for IMAGE-typed graphs.)
    allograph = models.ForeignKey("symbols_structure.Allograph", null=True, blank=True, on_delete=models.PROTECT)
    components = models.ManyToManyField(
        "symbols_structure.Component", related_name="graphs", through="GraphComponent", blank=True
    )
    positions = models.ManyToManyField("symbols_structure.Position", related_name="graphs", blank=True)
    hand = models.ForeignKey("scribes.Hand", null=True, blank=True, on_delete=models.PROTECT)

    # Fixed when the row is created (`save` refuses a change): to change a
    # graph's kind, make a new graph.
    annotation_type = models.CharField(
        max_length=20, choices=AnnotationType.choices, default=AnnotationType.IMAGE, db_index=True
    )
    # `null=True` lets the migration leave historical rows untouched —
    # they have no real creation date so claiming one would lie. New rows
    # get `auto_now_add`. Only used today by the texts-monitor annotation
    # sparkline, which silently ignores null-created rows.
    created = models.DateTimeField(auto_now_add=True, null=True, blank=True, db_index=True)

    # Subclasses LiveObjectsManager, so trashed rows stay hidden.
    objects = LiveObjectsManager.from_queryset(GraphQuerySet)()

    class Meta(SoftDeleteModel.Meta):
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                # Bare values: a nested Meta cannot see the enclosing class's AnnotationType.
                condition=models.Q(annotation_type__in=["image", "text", "editorial"]),
                name="graph_annotation_type_known",
            ),
            models.CheckConstraint(
                condition=models.Q(annotation_type__in=["editorial", "text"])
                | (models.Q(allograph__isnull=False) & models.Q(hand__isnull=False)),
                name="graph_editorial_or_required_allograph_hand",
            ),
        ]

    def __str__(self) -> str:
        return f"#{self.id} - {self.allograph} - {self.item_image}"

    @classmethod
    def from_db(cls, db, field_names, values, *args, **kwargs):
        instance = super().from_db(db, field_names, values, *args, **kwargs)
        # Deferred (`only()`) loads leave it out, and then there is nothing to compare.
        instance._loaded_annotation_type = instance.__dict__.get("annotation_type")
        return instance

    def save(self, *args, **kwargs):
        loaded = getattr(self, "_loaded_annotation_type", None)
        if loaded is not None and loaded != self.annotation_type:
            raise ValueError(f"Graph #{self.pk} is a {loaded} graph; a graph's kind is fixed when it is created.")
        super().save(*args, **kwargs)
        self._loaded_annotation_type = self.annotation_type

    def is_described(self) -> bool:
        """An image graph with at least one feature recorded on its components. Reads the
        `graphcomponent_set__features` prefetch where the caller has one."""
        return self.annotation_type == self.AnnotationType.IMAGE and any(
            gc.features.all() for gc in self.graphcomponent_set.all()
        )


class GraphComponent(models.Model):
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE)
    component = models.ForeignKey("symbols_structure.Component", on_delete=models.CASCADE)
    features = models.ManyToManyField("symbols_structure.Feature", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["graph", "component"], name="unique_graph_component"),
        ]

    def __str__(self) -> str:
        return f"#{self.graph_id} - {self.component}"


class GraphProposal(models.Model):
    """A machine-authored candidate annotation, awaiting a human decision.

    **A staging table, deliberately, rather than a status column on `Graph`.**
    A status flag would put every read path one forgotten filter away from
    serving unreviewed machine output as research data — and there is no way to
    audit a leak that never happened loudly. Here the canonical table simply
    does not contain proposals: a model cannot produce a `Graph`, only a
    candidate for one, and `accept()` is the sole path across. That makes the
    programme's human-in-the-loop guarantee (C1) a property of the schema
    instead of a property of everyone remembering.

    Distinct from the annotation-QC proposal's `GraphReview`, which reviews rows
    that are *already* canonical and explicitly never blocks a write. This is the
    gate in front; that is the audit behind.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    item_image = models.ForeignKey("manuscripts.ItemImage", related_name="graph_proposals", on_delete=models.CASCADE)
    annotation = models.JSONField()
    # SET_NULL: nothing can delete a proposal, so protecting them would stop a
    # rejected one ever letting go of a letter or a hand. Accepting one needs both.
    allograph = models.ForeignKey("symbols_structure.Allograph", null=True, blank=True, on_delete=models.SET_NULL)
    hand = models.ForeignKey("scribes.Hand", null=True, blank=True, on_delete=models.SET_NULL)
    annotation_type = models.CharField(
        max_length=20, choices=Graph.AnnotationType.choices, default=Graph.AnnotationType.IMAGE
    )
    confidence = models.FloatField(null=True, blank=True)

    # PROTECT: a proposal's provenance must stay resolvable. Deleting the ledger
    # row that produced it would leave a candidate nobody can attribute.
    ml_job = models.ForeignKey(
        "ml.MLJob",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="graph_proposals",
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="graph_proposals_reviewed",
    )
    reviewed = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    # The row this proposal became, if it was accepted. SET_NULL rather than
    # CASCADE: if the annotation is later trashed, the record that a human
    # accepted this proposal is still true and still worth keeping.
    accepted_graph = models.ForeignKey(Graph, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    # A reviewer may correct a pending proposal's letter, hand or box before
    # deciding it. What the model filed is kept here on the first correction
    # (`{"annotation": …, "allograph": id, "hand": id}`), so a model is judged
    # by what it proposed, not by what a person made of it. Null: uncorrected.
    proposed = models.JSONField(null=True, blank=True)
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="graph_proposals_corrected",
    )
    corrected = models.DateTimeField(null=True, blank=True)

    # Who asked the model about this shape in the viewer (W3.5). Theirs to settle,
    # there and then, so it stays out of the shared review queue. Null: bulk proposals.
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="graph_proposals_requested",
    )
    # What the model said beyond the columns above, as it said it: `components`,
    # `positions`, `reasoning`, `alternatives` and `problem`.
    description = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created"]
        indexes = [models.Index(fields=["item_image", "status"], name="proposal_image_status_idx")]

    def __str__(self) -> str:
        return f"proposal #{self.id} on image {self.item_image_id} ({self.status})"
