from haystack import indexes

from apps.manuscripts.models import ItemPart

# from apps.manuscripts.models import ItemImage, ItemPart


class ItemPartIndex(indexes.ModelSearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=False)
    id = indexes.IntegerField(model_attr="id")
    repository_name = indexes.CharField(model_attr="current_item__repository__name", faceted=True)
    repository_city = indexes.CharField(model_attr="current_item__repository__place", faceted=True)
    shelfmark = indexes.CharField(model_attr="current_item__shelfmark")
    catalogue_numbers = indexes.CharField(model_attr="historical_item", faceted=True)
    date = indexes.CharField(model_attr="historical_item__date")
    type = indexes.CharField(model_attr="historical_item__type", faceted=True)
    number_of_images = indexes.IntegerField(faceted=True)
    image_availability = indexes.CharField(faceted=True)
    issuer_name = indexes.CharField(model_attr="historical_item__issuer", faceted=True)
    named_beneficiary = indexes.CharField(model_attr="historical_item__named_beneficiary", faceted=True)

    def prepare_number_of_images(self, obj):
        return obj.images.count()

    def prepare_image_availability(self, obj):
        return "With images" if obj.images.exists() else "Without images"

    def prepare_catalogue_numbers(self, obj):
        return obj.historical_item.get_catalogue_numbers_display()

    def get_model(self):
        return ItemPart


# class ItemImageIndex(indexes.ModelSearchIndex, indexes.Indexable):
#     text = indexes.CharField(document=True, use_template=False)
#     id = indexes.IntegerField(model_attr="id")
#     image = indexes.CharField(model_attr="image")
#     locus = indexes.CharField(model_attr="locus", faceted=True)

#     repository_name = indexes.CharField(model_attr="item_part__current_item__repository__name", faceted=True)
#     repository_city = indexes.CharField(model_attr="item_part__current_item__repository__place", faceted=True)
#     shelfmark = indexes.CharField(model_attr="item_part__current_item__shelfmark")
#     date = indexes.CharField(model_attr="item_part__historical_item__date")
#     type = indexes.CharField(model_attr="item_part__historical_item__type", faceted=True)
#     issuer_name = indexes.CharField(model_attr="item_part__historical_item__issuer", faceted=True)
#     named_beneficiary = indexes.CharField(model_attr="item_part__historical_item__named_beneficiary", faceted=True)
#     number_of_annotations = indexes.IntegerField(model_attr="id", faceted=True)

#     components = indexes.MultiValueField(model_attr="id", faceted=True)
#     features = indexes.MultiValueField(model_attr="id", faceted=True)
#     component_feature = indexes.MultiValueField(model_attr="id", faceted=True)
#     positions = indexes.MultiValueField(model_attr="id", faceted=True)

#     def prepare_components(self, obj):
#         graphs = obj.graphs.all()
#         return [component.name for graph in graphs for component in graph.components.all()]

#     def prepare_features(self, obj):
#         graphs = obj.graphs.all()
#         return [feature.name for graph in graphs for feature in graph.features.all()]

#     def prepare_component_feature(self, obj):
#         graphs = obj.graphs.all()
#         return [
#             f"{component.name} - {feature.name}"
#             for graph in graphs
#             for component in graph.components.all()
#             for feature in graph.features.all()
#         ]

#     def prepare_positions(self, obj):
#         graphs = obj.graphs.all()
#         return [position.name for graph in graphs for position in graph.positions.all()]

#     def prepare_number_of_annotations(self, obj):
#         return obj.graphs.count()

#     def get_model(self):
#         return ItemImage
