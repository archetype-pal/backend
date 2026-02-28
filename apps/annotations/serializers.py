from rest_framework import serializers

from .models import Graph, GraphComponent


class GraphComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Graph.components.through
        fields = ["component", "features"]


class GraphSerializer(serializers.ModelSerializer):
    graphcomponent_set = GraphComponentSerializer(many=True)

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "annotation",
            "annotation_type",
            "allograph",
            "graphcomponent_set",
            "hand",
            "positions",
        ]

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


class GraphComponentManagementSerializer(serializers.ModelSerializer):
    component_name = serializers.CharField(source="component.name", read_only=True)

    class Meta:
        model = GraphComponent
        fields = ["id", "graph", "component", "component_name", "features"]


class GraphManagementSerializer(serializers.ModelSerializer):
    graphcomponent_set = GraphComponentManagementSerializer(many=True, read_only=True)
    allograph_name = serializers.StringRelatedField(source="allograph", read_only=True)
    hand_name = serializers.StringRelatedField(source="hand", read_only=True)
    image_display = serializers.StringRelatedField(source="item_image", read_only=True)
    historical_item = serializers.IntegerField(source="item_image.item_part.historical_item_id", read_only=True)

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "image_display",
            "historical_item",
            "annotation",
            "annotation_type",
            "allograph",
            "allograph_name",
            "hand",
            "hand_name",
            "positions",
            "graphcomponent_set",
        ]


class GraphWriteManagementSerializer(serializers.ModelSerializer):
    graphcomponent_set = GraphComponentSerializer(many=True, required=False)

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "annotation",
            "annotation_type",
            "allograph",
            "hand",
            "positions",
            "graphcomponent_set",
        ]

    def create(self, validated_data):
        components_data = validated_data.pop("graphcomponent_set", [])
        positions_data = validated_data.pop("positions", [])
        graph = Graph.objects.create(**validated_data)
        graph.positions.set(positions_data)
        for comp_data in components_data:
            features_data = comp_data.pop("features", [])
            graph_component = GraphComponent.objects.create(graph=graph, **comp_data)
            graph_component.features.set(features_data)
        return graph

    def update(self, instance, validated_data):
        components_data = validated_data.pop("graphcomponent_set", None)
        positions_data = validated_data.pop("positions", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if positions_data is not None:
            instance.positions.set(positions_data)

        if components_data is not None:
            instance.graphcomponent_set.all().delete()
            for comp_data in components_data:
                features_data = comp_data.pop("features", [])
                graph_component = GraphComponent.objects.create(graph=instance, **comp_data)
                graph_component.features.set(features_data)

        return instance
