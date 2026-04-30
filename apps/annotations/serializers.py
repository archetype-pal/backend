from rest_framework import serializers

from apps.symbols_structure.models import Position

from .models import Graph, GraphComponent
from .services import GraphWriteService


class GraphDescriptionMixin:
    def get_num_features(self, obj):
        # Prefer the Count annotation from the queryset; fall back to computing from prefetched data
        annotated = getattr(obj, "num_features", None)
        if annotated is not None:
            return annotated
        return sum(gc.features.count() for gc in obj.graphcomponent_set.all())

    def get_is_described(self, obj):
        return self.get_num_features(obj) > 0

    def get_position_details(self, obj):
        return [{"id": position.id, "name": position.name} for position in obj.positions.all()]


class GraphComponentDescriptionMixin:
    def get_feature_details(self, obj):
        return [{"id": feature.id, "name": feature.name} for feature in obj.features.all()]


class GraphComponentSerializer(GraphComponentDescriptionMixin, serializers.ModelSerializer):
    component_name = serializers.CharField(source="component.name", read_only=True)
    feature_details = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = GraphComponent
        fields = ["component", "component_name", "features", "feature_details"]


class GraphAnnotationRulesMixin:
    def _resolve_annotation_type(self, attrs):
        instance = getattr(self, "instance", None)
        return attrs.get("annotation_type") or getattr(instance, "annotation_type", None) or Graph.AnnotationType.IMAGE

    def validate(self, attrs):
        attrs = super().validate(attrs)
        annotation_type = self._resolve_annotation_type(attrs)
        attrs["annotation_type"] = annotation_type

        if annotation_type == Graph.AnnotationType.EDITORIAL:
            attrs["note"] = ""
            return attrs

        instance = getattr(self, "instance", None)
        allograph = attrs.get("allograph", getattr(instance, "allograph", None))
        hand = attrs.get("hand", getattr(instance, "hand", None))
        errors = {}

        if allograph is None:
            errors["allograph"] = "This field is required for standard annotations."
        if hand is None:
            errors["hand"] = "This field is required for standard annotations."

        if errors:
            raise serializers.ValidationError(errors)

        attrs["internal_note"] = ""
        return attrs


class GraphSerializer(GraphDescriptionMixin, serializers.ModelSerializer):
    graphcomponent_set = GraphComponentSerializer(many=True, read_only=True)
    allograph_name = serializers.CharField(source="allograph.name", read_only=True, allow_null=True)
    internal_note = serializers.SerializerMethodField(read_only=True)
    position_details = serializers.SerializerMethodField(read_only=True)
    num_features = serializers.SerializerMethodField()
    is_described = serializers.SerializerMethodField()

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "annotation",
            "annotation_type",
            "note",
            "internal_note",
            "allograph",
            "allograph_name",
            "graphcomponent_set",
            "hand",
            "positions",
            "position_details",
            "num_features",
            "is_described",
        ]

    def get_internal_note(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False):
            return obj.internal_note
        return ""

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


class GraphComponentManagementSerializer(
    GraphComponentDescriptionMixin, GraphDescriptionMixin, serializers.ModelSerializer
):
    component_name = serializers.CharField(source="component.name", read_only=True)
    feature_details = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = GraphComponent
        fields = ["id", "graph", "component", "component_name", "features", "feature_details"]


class GraphManagementSerializer(GraphDescriptionMixin, serializers.ModelSerializer):
    graphcomponent_set = GraphComponentManagementSerializer(many=True, read_only=True)
    allograph_name = serializers.CharField(source="allograph.name", read_only=True, allow_null=True)
    hand_name = serializers.StringRelatedField(source="hand", read_only=True)
    image_display = serializers.StringRelatedField(source="item_image", read_only=True)
    historical_item = serializers.IntegerField(source="item_image.item_part.historical_item_id", read_only=True)
    position_details = serializers.SerializerMethodField(read_only=True)
    num_features = serializers.SerializerMethodField()
    is_described = serializers.SerializerMethodField()

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "image_display",
            "historical_item",
            "annotation",
            "annotation_type",
            "note",
            "internal_note",
            "allograph",
            "allograph_name",
            "hand",
            "hand_name",
            "positions",
            "position_details",
            "graphcomponent_set",
            "num_features",
            "is_described",
        ]


class GraphWriteManagementSerializer(GraphAnnotationRulesMixin, GraphDescriptionMixin, serializers.ModelSerializer):
    graphcomponent_set = GraphComponentSerializer(many=True, required=False)
    num_features = serializers.SerializerMethodField(read_only=True)
    is_described = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "annotation",
            "annotation_type",
            "note",
            "internal_note",
            "allograph",
            "hand",
            "positions",
            "graphcomponent_set",
            "num_features",
            "is_described",
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


class GraphViewerWriteSerializer(GraphAnnotationRulesMixin, GraphDescriptionMixin, serializers.ModelSerializer):
    graphcomponent_set = GraphComponentSerializer(many=True, required=False)
    positions = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Position.objects.all(),
        required=False,
        allow_empty=True,
    )
    num_features = serializers.SerializerMethodField(read_only=True)
    is_described = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "annotation",
            "annotation_type",
            "note",
            "internal_note",
            "allograph",
            "hand",
            "positions",
            "graphcomponent_set",
            "num_features",
            "is_described",
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
