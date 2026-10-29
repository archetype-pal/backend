from django.db import transaction
from rest_framework import serializers

from .models import Graph, GraphComponent


class NamedSerializer(serializers.Serializer):
    """`{"id", "name"}` of a Position or Feature."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class GraphDescriptionFields(serializers.Serializer):
    """Read-only description fields shared by every Graph serializer.

    A `Serializer` rather than a plain mixin so its declared fields are
    inherited; the viewsets annotate `num_features`, and the fallback keeps
    ad-hoc serialization correct.
    """

    allograph_name = serializers.CharField(source="allograph.name", read_only=True, allow_null=True)
    position_details = NamedSerializer(source="positions", many=True, read_only=True)
    num_features = serializers.SerializerMethodField()
    is_described = serializers.SerializerMethodField()

    def get_num_features(self, obj) -> int:
        annotated = getattr(obj, "num_features", None)
        if annotated is not None:
            return int(annotated)
        return sum(gc.features.count() for gc in obj.graphcomponent_set.all())

    def get_is_described(self, obj) -> bool:
        return self.get_num_features(obj) > 0


class GraphComponentSerializer(serializers.ModelSerializer):
    component_name = serializers.CharField(source="component.name", read_only=True)
    feature_details = NamedSerializer(source="features", many=True, read_only=True)

    class Meta:
        model = GraphComponent
        fields = ["component", "component_name", "features", "feature_details"]


class GraphAnnotationRulesMixin:
    def _resolve_annotation_type(self, attrs):
        instance = getattr(self, "instance", None)
        return attrs.get("annotation_type") or getattr(instance, "annotation_type", None) or Graph.AnnotationType.IMAGE

    def validate_item_image(self, value):
        # The polygon is in the pixel coordinates of this image only.
        instance = getattr(self, "instance", None)
        if instance is not None and value.pk != instance.item_image_id:
            raise serializers.ValidationError("An annotation cannot be moved to another image.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        annotation_type = self._resolve_annotation_type(attrs)
        attrs["annotation_type"] = annotation_type

        if annotation_type == Graph.AnnotationType.EDITORIAL:
            attrs["note"] = ""
            return attrs

        # TEXT graphs are bare regions referenced from the transcription; they
        # carry no allograph/hand, so the standard-annotation requirement below
        # doesn't apply (e.g. a region reshape via the viewer's geometry PATCH).
        if annotation_type == Graph.AnnotationType.TEXT:
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


class GraphSerializer(GraphDescriptionFields, serializers.ModelSerializer):
    graphcomponent_set = GraphComponentSerializer(many=True, read_only=True)
    item_part = serializers.IntegerField(source="item_image.item_part_id", read_only=True)
    # Each graph's own source image — required so a multi-manuscript selection
    # can preview/crop every graph from its correct image (see
    # build_graph_document for the search-index equivalent).
    image_iiif = serializers.CharField(source="item_image.image.iiif.info", read_only=True, default=None)
    internal_note = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Graph
        fields = [
            "id",
            "item_image",
            "item_part",
            "image_iiif",
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


class GraphComponentManagementSerializer(GraphComponentSerializer):
    class Meta(GraphComponentSerializer.Meta):
        fields = ["id", "graph", *GraphComponentSerializer.Meta.fields]


class GraphManagementSerializer(GraphDescriptionFields, serializers.ModelSerializer):
    graphcomponent_set = GraphComponentManagementSerializer(many=True, read_only=True)
    hand_name = serializers.StringRelatedField(source="hand", read_only=True)
    image_display = serializers.StringRelatedField(source="item_image", read_only=True)
    historical_item = serializers.IntegerField(source="item_image.item_part.historical_item_id", read_only=True)
    deleted_by = serializers.SlugRelatedField(slug_field="username", read_only=True)

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
            "created",
            "deleted_at",
            "deleted_by",
        ]
        read_only_fields = ["created", "deleted_at", "deleted_by"]


def _replace_graph_components(graph: Graph, components_data: list[dict]) -> None:
    for component_data in components_data:
        component_payload = dict(component_data)
        features_data = component_payload.pop("features", [])
        graph_component = GraphComponent.objects.create(graph=graph, **component_payload)
        graph_component.features.set(features_data)


class GraphWriteMixin:
    """Create/update a Graph aggregate with its nested components + positions.

    Plain ORM — there is no cross-aggregate orchestration or transaction to
    justify a separate service layer, so the write lives with the serializer.
    """

    def create(self, validated_data):
        components_data = validated_data.pop("graphcomponent_set", [])
        positions_data = validated_data.pop("positions", [])
        with transaction.atomic():
            graph = Graph.objects.create(**validated_data)
            graph.positions.set(positions_data)
            _replace_graph_components(graph, components_data)
        return graph

    def update(self, instance, validated_data):
        components_data = validated_data.pop("graphcomponent_set", None)
        positions_data = validated_data.pop("positions", None)
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            if positions_data is not None:
                instance.positions.set(positions_data)
            if components_data is not None:
                instance.graphcomponent_set.all().delete()
                _replace_graph_components(instance, components_data)
        return instance


class GraphWriteManagementSerializer(
    GraphWriteMixin, GraphAnnotationRulesMixin, GraphDescriptionFields, serializers.ModelSerializer
):
    graphcomponent_set = GraphComponentSerializer(many=True, required=False)

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


class GraphViewerWriteSerializer(GraphWriteManagementSerializer):
    """The viewer's write serializer: the management one plus the labels the viewer renders back."""

    item_part = serializers.IntegerField(source="item_image.item_part_id", read_only=True)

    class Meta(GraphWriteManagementSerializer.Meta):
        fields = [*GraphWriteManagementSerializer.Meta.fields, "item_part", "allograph_name"]
