import json

from rest_framework import serializers

from apps.common.mixins import CustomFacetMixin as FacetMixin
from apps.manuscripts.iiif import get_iiif_cropped_url
from haystack_rest.filters import HaystackFilter, HaystackOrderingFilter
from haystack_rest.serializers import HaystackFacetSerializer, HaystackSerializer
from haystack_rest.viewsets import HaystackViewSet

from .models import Graph
from .search_indexes import GraphIndex


class GraphSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")
    coordinates = serializers.JSONField()
    image_url = serializers.SerializerMethodField()
    component_features_display = serializers.SerializerMethodField()

    class Meta:
        index_classes = [GraphIndex]

        fields = [
            "id",
            "item_image",
            "coordinates",
            "is_annotated",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date",
            "image_url",
            "allograph",
            "character",
            "character_type",
            "hand_name",
            "component_features",
            "component_features_display",
        ]

    def get_image_url(self, obj):
        """
        Generate a cropped IIIF image URL based on the graph's coordinates.
        """
        try:
            # Get the image path from the search result (indexed field)
            image_path = None
            if hasattr(obj, "image_path") and obj.image_path:
                image_path = obj.image_path
            else:
                # Fallback: get from the model object
                graph = obj.object
                image_path = str(graph.item_image.image)

            # Get coordinates from the search result (indexed field)
            coordinates_json = None
            if hasattr(obj, "coordinates") and obj.coordinates:
                coordinates_json = obj.coordinates
            else:
                # Fallback: get from the model object
                graph = obj.object
                coordinates_json = graph.annotation

            if not image_path or not coordinates_json:
                return None

            # If coordinates_json is already a dict, convert to string for the helper function
            if isinstance(coordinates_json, dict):
                coordinates_json = json.dumps(coordinates_json)
            elif not isinstance(coordinates_json, str):
                return None

            # Construct the cropped IIIF URL
            return get_iiif_cropped_url(str(image_path), coordinates_json)
        except (AttributeError, KeyError, ValueError, TypeError):
            # If anything goes wrong, return None
            return None

    def get_component_features_display(self, obj):
        """
        Format component-feature pairs for hover tooltip display.
        Returns a string like "Component: Feature, Component: Feature"
        """
        try:
            component_features = None
            if hasattr(obj, "component_features") and obj.component_features:
                # Indexed format is "Component - Feature", convert to "Component: Feature"
                component_features = [cf.replace(" - ", ": ") if " - " in cf else cf for cf in obj.component_features]
            else:
                # Fallback: get from the model object
                graph = obj.object
                graph_components = graph.graphcomponent_set.select_related("component").prefetch_related("features")
                component_features = []
                for gc in graph_components:
                    for feature in gc.features.all():
                        component_features.append(f"{gc.component.name}: {feature.name}")

            if component_features:
                # Format as "Component: Feature, Component: Feature"
                return ", ".join(component_features)
            return None
        except (AttributeError, KeyError, ValueError, TypeError):
            return None


class GraphFacetSearchSerializer(HaystackFacetSerializer):
    serialize_objects = True

    class Meta:
        fields = [
            "repository_city",
            "repository_name",
            "allograph",
            "character",
            "character_type",
            "components",
            "features",
            "component_features",
            "positions",
        ]
        field_options = {
            "repository_city": {},
            "repository_name": {},
            "allograph": {},
            "character": {},
            "character_type": {},
            "components": {},
            "features": {},
            "component_features": {},
            "positions": {},
        }


class GraphSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [Graph]
    serializer_class = GraphSearchSerializer
    facet_serializer_class = GraphFacetSearchSerializer
    filter_backends = [HaystackFilter, HaystackOrderingFilter]

    ordering_fields = [
        "repository_name_exact",
        "repository_city_exact",
        "shelfmark_exact",
        "allograph_exact",
    ]
