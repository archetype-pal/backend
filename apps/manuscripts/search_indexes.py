from haystack import indexes

from apps.annotations.models import GraphComponent
from apps.manuscripts.models import ItemImage, ItemPart


class ItemPartIndex(indexes.ModelSearchIndex, indexes.Indexable):
    model_id = indexes.IntegerField(model_attr="id")
    repository_name = indexes.CharField(model_attr="current_item__repository__name", faceted=True)
    repository_city = indexes.CharField(model_attr="current_item__repository__place", faceted=True)
    shelfmark = indexes.CharField(model_attr="current_item__shelfmark")
    catalogue_numbers = indexes.CharField(model_attr="historical_item", faceted=True)
    date = indexes.CharField(model_attr="historical_item__date__date")
    # Fields related to the `Date` model
    date_min = indexes.IntegerField(model_attr="historical_item__date__min_weight", faceted=True)
    date_max = indexes.IntegerField(model_attr="historical_item__date__max_weight", faceted=True)
    type = indexes.CharField(model_attr="historical_item__type", faceted=True)
    format = indexes.CharField(model_attr="historical_item__format__name", faceted=True)
    number_of_images = indexes.IntegerField(faceted=True)
    image_availability = indexes.CharField(faceted=True)

    class Meta:
        model = ItemPart

    def prepare_number_of_images(self, obj):
        return obj.images.count()

    def prepare_image_availability(self, obj):
        return "With images" if obj.images.exists() else "Without images"

    def prepare_catalogue_numbers(self, obj):
        return obj.historical_item.get_catalogue_numbers_display()

        # Extract and serialize the `Date` model fields

    def prepare_date(self, obj):
        if obj.historical_item.date:
            return obj.historical_item.date.date  # Returns the `date` string (e.g., "1000x1001")
        return None

    def prepare_date_min(self, obj):
        if obj.historical_item and obj.historical_item.date and obj.historical_item.date.min_weight:
            return obj.historical_item.date.min_weight
        return None  # Default value

    def prepare_date_max(self, obj):
        if obj.historical_item and obj.historical_item.date and obj.historical_item.date.max_weight:
            return obj.historical_item.date.max_weight
        return None  # Default value


class ItemImageIndex(indexes.ModelSearchIndex, indexes.Indexable):
    model_id = indexes.IntegerField(model_attr="id")
    image = indexes.CharField(model_attr="image")
    thumbnail = indexes.CharField(model_attr="image")
    locus = indexes.CharField(model_attr="locus", faceted=True)

    repository_name = indexes.CharField(model_attr="item_part__current_item__repository__name", faceted=True)
    repository_city = indexes.CharField(model_attr="item_part__current_item__repository__place", faceted=True)
    shelfmark = indexes.CharField(model_attr="item_part__current_item__shelfmark")
    date = indexes.CharField(model_attr="item_part__historical_item__date__date")
    type = indexes.CharField(model_attr="item_part__historical_item__type", faceted=True)
    number_of_annotations = indexes.IntegerField(model_attr="id", faceted=True)

    components = indexes.MultiValueField(model_attr="id", faceted=True)
    features = indexes.MultiValueField(model_attr="id", faceted=True)
    component_features = indexes.MultiValueField(model_attr="id", faceted=True)
    positions = indexes.MultiValueField(model_attr="id", faceted=True)

    class Meta:
        model = ItemImage

    def prepare_components(self, obj):
        graphs = obj.graphs.all()
        return [component.name for graph in graphs for component in graph.components.all()]

    def prepare_thumbnail(self, obj):
        return obj.image.iiif.thumbnail

    def prepare_features(self, obj):
        result = []
        graphs = obj.graphs.all()
        for graph in graphs:
            graph_components = GraphComponent.objects.filter(graph=graph).prefetch_related("features")
            for gc in graph_components:
                result.extend([feature.name for feature in gc.features.all()])
        return result

    def prepare_component_features(self, obj):
        result = []
        graphs = obj.graphs.all()

        for graph in graphs:
            graph_components = GraphComponent.objects.filter(graph=graph).select_related("component").prefetch_related("features")
            for gc in graph_components:
                for feature in gc.features.all():
                    result.append(f"{gc.component.name} - {feature.name}")

        return result

    def prepare_positions(self, obj):
        graphs = obj.graphs.all()
        return [position.name for graph in graphs for position in graph.positions.all()]

    def prepare_number_of_annotations(self, obj):
        return obj.graphs.count()
