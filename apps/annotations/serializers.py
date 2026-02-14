from rest_framework import serializers

from .models import Graph


class GraphComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Graph.components.through
        fields = ["component", "features"]


class GraphSerializer(serializers.ModelSerializer):
    graphcomponent_set = GraphComponentSerializer(many=True)

    class Meta:
        model = Graph
        fields = ["id", "item_image", "annotation", "annotation_type", "allograph", "graphcomponent_set", "hand", "positions"]

    def create(self, validated_data):
        components_data = validated_data.pop("graphcomponent_set")
        positions_ids = validated_data.pop("positions")
        graph = Graph.objects.create(**validated_data)
        graph.positions.set(positions_ids)
        for component_data in components_data:
            features_data = component_data.pop("features")
            component = Graph.components.through.objects.create(graph=graph, **component_data)
            component.features.set(features_data)
        return graph
