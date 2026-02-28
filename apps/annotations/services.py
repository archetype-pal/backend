"""Application services for annotation write workflows."""

from typing import Any, cast

from apps.annotations.models import Graph, GraphComponent


class GraphWriteService:
    """Create/update Graph aggregates and nested components."""

    def create_graph(
        self,
        *,
        graph_data: dict[str, Any],
        components_data: list[dict[str, Any]],
        positions_data: list[Any],
    ) -> Graph:
        graph = cast(Graph, Graph.objects.create(**graph_data))
        graph.positions.set(positions_data)
        self._replace_components(graph=graph, components_data=components_data)
        return graph

    def update_graph(
        self,
        *,
        graph: Graph,
        graph_data: dict[str, Any],
        components_data: list[dict[str, Any]] | None,
        positions_data: list[Any] | None,
    ) -> Graph:
        for attr, value in graph_data.items():
            setattr(graph, attr, value)
        graph.save()
        if positions_data is not None:
            graph.positions.set(positions_data)
        if components_data is not None:
            graph.graphcomponent_set.all().delete()
            self._replace_components(graph=graph, components_data=components_data)
        return graph

    def _replace_components(self, *, graph: Graph, components_data: list[dict[str, Any]]) -> None:
        for component_data in components_data:
            component_payload = dict(component_data)
            features_data = component_payload.pop("features", [])
            graph_component = GraphComponent.objects.create(graph=graph, **component_payload)
            graph_component.features.set(features_data)
