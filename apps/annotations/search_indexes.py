from haystack import indexes

from .models import Graph


class GraphIndex(indexes.ModelSearchIndex, indexes.Indexable):
    model_id = indexes.IntegerField(model_attr="id")
    item_image = indexes.IntegerField(model_attr="item_image__id")
    coordinates = indexes.CharField(model_attr="annotation")
    is_annotated = indexes.BooleanField(model_attr="is_annotated")

    repository_name = indexes.CharField(
        model_attr="item_image__item_part__current_item__repository__name", faceted=True
    )
    repository_city = indexes.CharField(
        model_attr="item_image__item_part__current_item__repository__place", faceted=True
    )
    shelfmark = indexes.CharField(model_attr="item_image__item_part__current_item__shelfmark")
    date = indexes.CharField(model_attr="item_image__item_part__historical_item__date__date")
    place = indexes.CharField(model_attr="hand__place", faceted=True)
    components = indexes.MultiValueField(model_attr="id", faceted=True)
    features = indexes.MultiValueField(model_attr="id", faceted=True)
    component_features = indexes.MultiValueField(model_attr="id", faceted=True)
    positions = indexes.MultiValueField(model_attr="id", faceted=True)

    allograph = indexes.CharField(model_attr="allograph__name", faceted=True)
    character = indexes.CharField(model_attr="allograph__character__name", faceted=True)
    character_type = indexes.CharField(model_attr="allograph__character__type", faceted=True)

    class Meta:
        model = Graph

    def prepare_components(self, obj):
        return [component.name for component in obj.components.all()]

    def prepare_thumbnail(self, obj):
        return obj.image.iiif.thumbnail

    def prepare_features(self, obj):
        [feature.name for component in obj.components.all() for feature in component.features.all()]

    def prepare_component_features(self, obj):
        return [
            f"{component.name} - {feature.name}" for component in obj.components.all() for feature in obj.features.all()
        ]

    def prepare_positions(self, obj):
        return [position.name for position in obj.positions.all()]
