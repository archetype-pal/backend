from django.db import models


class Graph(models.Model):
    class AnnotationType(models.TextChoices):
        IMAGE = "image", "Image"
        TEXT = "text", "Text"
        EDITORIAL = "editorial", "Editorial"
        UNKNOWN = "unknown", "Unknown"

    item_image = models.ForeignKey("manuscripts.ItemImage", related_name="graphs", on_delete=models.CASCADE)
    annotation = models.JSONField()  # rename this to location
    note = models.TextField(blank=True, default="")
    internal_note = models.TextField(blank=True, default="")
    # The paleographic FKs below are required for IMAGE-typed graphs (a glyph
    # instance with allograph + scribal hand) but null for EDITORIAL and TEXT
    # rows. TEXT graphs are just regions on the image referenced from
    # `ImageText.content` via `data-graph-id` attributes on a span.
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

    annotation_type = models.CharField(
        max_length=20, choices=AnnotationType.choices, null=True, blank=True, db_index=True
    )
    # `null=True` lets the migration leave historical rows untouched —
    # they have no real creation date so claiming one would lie. New rows
    # get `auto_now_add`. Only used today by the texts-monitor annotation
    # sparkline, which silently ignores null-created rows.
    created = models.DateTimeField(auto_now_add=True, null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(annotation_type__in=["editorial", "text"])
                | (models.Q(allograph__isnull=False) & models.Q(hand__isnull=False)),
                name="graph_editorial_or_required_allograph_hand",
            ),
        ]

    def __str__(self) -> str:
        return f"#{self.id} - {self.allograph} - {self.item_image}"

    def is_annotated(self) -> bool:
        """
        Check if the graph has been annotated with components, or positions.
        """
        return bool(self.components.exists() or self.positions.exists())


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
