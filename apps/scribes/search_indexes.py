# from haystack import indexes

# from apps.scribes.models import Hand, Scribe


# class ScribeIndex(indexes.SearchIndex, indexes.Indexable):
#     text = indexes.CharField(document=True, use_template=False)
#     id = indexes.IntegerField(model_attr="id")
#     name = indexes.CharField(model_attr="name")
#     period = indexes.CharField(model_attr="period")
#     scriptorium = indexes.CharField(model_attr="scriptorium", faceted=True)

#     class Meta:
#         model = Scribe

#     def get_model(self):
#         return Scribe


# class HandIndex(indexes.SearchIndex, indexes.Indexable):
#     text = indexes.CharField(document=True, use_template=False)
#     id = indexes.IntegerField(model_attr="id")
#     name = indexes.CharField(model_attr="name")
#     date = indexes.CharField(model_attr="date")
#     place = indexes.CharField(model_attr="place", faceted=True)
#     description = indexes.CharField(model_attr="description")
#     repository_name = indexes.CharField(model_attr="item_part__current_item__repository__name", faceted=True)
#     repository_city = indexes.CharField(model_attr="item_part__current_item__repository__place", faceted=True)
#     shelfmark = indexes.CharField(model_attr="item_part__current_item__shelfmark")
#     catalogue_numbers = indexes.CharField(model_attr="item_part__historical_item", faceted=True)

#     def prepare_catalogue_numbers(self, obj):
#         return [str(cn) for cn in obj.item_part.historical_item.catalogue_numbers.all()]

#     def get_model(self):
#         return Hand
