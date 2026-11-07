from datetime import datetime, time

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import Graph, GraphComponent, GraphProposal
from .services import proposals


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
        # `Graph.is_described()`, from the annotated count rather than a prefetch.
        return obj.annotation_type == Graph.AnnotationType.IMAGE and self.get_num_features(obj) > 0


class GraphComponentSerializer(serializers.ModelSerializer):
    component_name = serializers.CharField(source="component.name", read_only=True)
    feature_details = NamedSerializer(source="features", many=True, read_only=True)

    class Meta:
        model = GraphComponent
        fields = ["component", "component_name", "features", "feature_details"]


class GraphAnnotationRulesMixin:
    def _resolve_annotation_type(self, attrs):
        instance = getattr(self, "instance", None)
        return attrs.get("annotation_type", instance.annotation_type if instance else Graph.AnnotationType.IMAGE)

    def validate_annotation_type(self, value):
        instance = getattr(self, "instance", None)
        if instance is not None and value != instance.annotation_type:
            raise serializers.ValidationError("An annotation's kind is fixed when it is created.")
        return value

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

    A CRUD route's write, so it lives in the serializer hooks (CONTRIBUTING's
    rule for where writes live). The transaction makes the graph, its
    positions and its components land together.
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
    # The proposal this annotation came from, when a model was asked about the shape (W3.5).
    suggestion = serializers.IntegerField(write_only=True, required=False, min_value=1)

    class Meta(GraphWriteManagementSerializer.Meta):
        fields = [*GraphWriteManagementSerializer.Meta.fields, "item_part", "allograph_name", "suggestion"]

    def create(self, validated_data):
        suggestion = validated_data.pop("suggestion", None)
        with transaction.atomic():
            graph = super().create(validated_data)
            if suggestion is not None:
                proposals.adopt(suggestion, graph=graph, reviewer=self.context["request"].user)
        return graph

    def update(self, instance, validated_data):
        suggestion = validated_data.pop("suggestion", None)
        with transaction.atomic():
            graph = super().update(instance, validated_data)
            if suggestion is not None:
                proposals.adopt(suggestion, graph=graph, reviewer=self.context["request"].user)
        return graph


class GraphProposalSerializer(serializers.ModelSerializer):
    """Read shape for the proposal review queue.

    Carries what a reviewer judges a proposal by: the page it sits on (its IIIF
    identifier, so the queue can crop the box), the letter and hand it names,
    and the model that produced it. Without these the queue would be a list of
    ids, each needing three more requests before anyone could decide it.
    """

    reviewer_username = serializers.CharField(source="reviewer.username", read_only=True, default="")
    allograph_name = serializers.CharField(source="allograph.name", read_only=True, allow_null=True)
    hand_name = serializers.StringRelatedField(source="hand", read_only=True)
    image_display = serializers.StringRelatedField(source="item_image", read_only=True)
    # The same source `GraphSerializer` crops graphs from.
    image_iiif = serializers.CharField(source="item_image.image.iiif.info", read_only=True, default=None)
    historical_item = serializers.IntegerField(source="item_image.item_part.historical_item_id", read_only=True)
    # The part whose hands a correction may name.
    item_part = serializers.IntegerField(source="item_image.item_part_id", read_only=True)
    model_name = serializers.CharField(source="ml_job.model_name", read_only=True, default="")
    corrected_by_username = serializers.CharField(source="corrected_by.username", read_only=True, default="")

    class Meta:
        model = GraphProposal
        fields = (
            "id",
            "item_image",
            "image_display",
            "image_iiif",
            "historical_item",
            "item_part",
            "annotation",
            "allograph",
            "allograph_name",
            "hand",
            "hand_name",
            "annotation_type",
            "confidence",
            "ml_job",
            "model_name",
            "status",
            "reviewer",
            "reviewer_username",
            "reviewed",
            "reason",
            "accepted_graph",
            "created",
            "proposed",
            "corrected_by",
            "corrected_by_username",
            "corrected",
        )
        # Every field is machine-written or set by a decision or correction
        # action; nothing here is editable through the CRUD routes.
        read_only_fields = fields


class GraphProposalCorrectionSerializer(serializers.ModelSerializer):
    """Input for correcting a pending proposal: any of its letter, hand and box.

    A model serializer for the related fields' lookups only (this app does not
    import the glyph taxonomy or the hands); it is never saved; the view hands
    the validated values to `proposals.correct`.
    """

    class Meta:
        model = GraphProposal
        fields = ("allograph", "hand", "annotation")
        extra_kwargs = {
            "allograph": {"required": False, "allow_null": False},
            "hand": {"required": False, "allow_null": False},
            "annotation": {"required": False},
        }

    def validate_hand(self, hand):
        # Whose letter it is: a hand of this page's own manuscript part.
        if hand.item_part_id != self.instance.item_image.item_part_id:
            raise serializers.ValidationError("This hand is not one of this page's hands.")
        return hand

    def validate_annotation(self, annotation):
        """The box as the platform stores it: a GeoJSON polygon of one closed ring, in the page's pixels."""
        geometry = annotation.get("geometry") if isinstance(annotation, dict) else None
        rings = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not (
            isinstance(geometry, dict)
            and annotation.get("type") == "Feature"
            and geometry.get("type") == "Polygon"
            and isinstance(rings, list)
            and len(rings) == 1
            and isinstance(rings[0], list)
        ):
            raise serializers.ValidationError("Expected a GeoJSON Feature with a Polygon of one ring.")
        ring = rings[0]
        if not all(
            isinstance(point, list)
            and len(point) == 2
            and all(isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v < 1e6 for v in point)
            for point in ring
        ):
            raise serializers.ValidationError("Each point is a pair of pixel coordinates, neither negative.")
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise serializers.ValidationError("The ring must be closed: at least four points, the last the first.")
        # The shoelace area: a ring folded onto a line or a point outlines nothing.
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:], strict=False)) / 2
        if abs(area) < 1:
            raise serializers.ValidationError("The box encloses no area.")
        return annotation

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Name a letter, a hand or a box to correct.")
        return attrs


class ProposalThroughputQuerySerializer(serializers.Serializer):
    """The window a throughput report covers: from `since` to `until` (or now), both whole days."""

    since = serializers.DateField()
    until = serializers.DateField(required=False)

    def validate(self, attrs):
        def start_of(day):
            return timezone.make_aware(datetime.combine(day, time.min))

        since = start_of(attrs["since"])
        until = start_of(attrs["until"]) if "until" in attrs else timezone.now()
        if until <= since:
            raise serializers.ValidationError({"until": "The window must end after it starts."})
        return {"since": since, "until": until}
