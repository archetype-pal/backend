from django.db import models


class Graph(models.Model):
    item_image = models.ForeignKey("manuscripts.ItemImage", related_name="graphs", on_delete=models.CASCADE)
    annotation = models.JSONField()
    allograph = models.ForeignKey("symbols_structure.Allograph", on_delete=models.CASCADE)
    components = models.ManyToManyField(
        "symbols_structure.Component", related_name="graphs", through="GraphComponent", blank=True
    )
    positions = models.ManyToManyField("symbols_structure.Position", related_name="graphs")
    hand = models.ForeignKey("scribes.Hand", on_delete=models.PROTECT)

    def __str__(self) -> str:
        return f"#{self.id} - {self.allograph} - {self.item_image}"


class GraphComponent(models.Model):
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE)
    component = models.ForeignKey("symbols_structure.Component", on_delete=models.CASCADE)
    features = models.ManyToManyField("symbols_structure.Feature", blank=True)

    class Meta:
        unique_together = ("graph", "component")
