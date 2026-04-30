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
    # the fields below annotate the graph described by the image and its location above
    allograph = models.ForeignKey("symbols_structure.Allograph", null=True, blank=True, on_delete=models.CASCADE)
    components = models.ManyToManyField(
        "symbols_structure.Component", related_name="graphs", through="GraphComponent", blank=True
    )
    positions = models.ManyToManyField("symbols_structure.Position", related_name="graphs")
    hand = models.ForeignKey("scribes.Hand", null=True, blank=True, on_delete=models.PROTECT)

    annotation_type = models.CharField(
        max_length=20, choices=AnnotationType.choices, null=True, blank=True, db_index=True
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(annotation_type="editorial")
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
