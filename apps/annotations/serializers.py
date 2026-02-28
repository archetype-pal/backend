from rest_framework import serializers

from .models import Graph, GraphComponent
from .services import GraphWriteService


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

    @staticmethod
    def _service() -> GraphWriteService:
        return GraphWriteService()

    def create(self, validated_data):
        components_data = validated_data.pop("graphcomponent_set")
        positions_ids = validated_data.pop("positions")
        return self._service().create_graph(
            graph_data=validated_data,
            components_data=components_data,
            positions_data=positions_ids,
        )


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

    @staticmethod
    def _service() -> GraphWriteService:
        return GraphWriteService()

    def create(self, validated_data):
        components_data = validated_data.pop("graphcomponent_set", [])
        positions_data = validated_data.pop("positions", [])
        return self._service().create_graph(
            graph_data=validated_data,
            components_data=components_data,
            positions_data=positions_data,
        )

    def update(self, instance, validated_data):
        components_data = validated_data.pop("graphcomponent_set", None)
        positions_data = validated_data.pop("positions", None)
        return self._service().update_graph(
            graph=instance,
            graph_data=validated_data,
            components_data=components_data,
            positions_data=positions_data,
        )
