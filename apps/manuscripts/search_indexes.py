from haystack import indexes

from apps.manuscripts.models import ItemPart


class ItemPartIndex(indexes.ModelSearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=False)
    id = indexes.IntegerField(model_attr="id")
    repository_name = indexes.CharField(model_attr="current_item__repository__name", faceted=True)
    repository_city = indexes.CharField(model_attr="current_item__repository__place", faceted=True)
    shelfmark = indexes.CharField(model_attr="current_item__shelfmark")
    catalogue_numbers = indexes.CharField(model_attr="historical_item", faceted=True)
    date = indexes.CharField(model_attr="historical_item__date")
    type = indexes.CharField(model_attr="historical_item__type", faceted=True)
    number_of_images = indexes.IntegerField(model_attr="id", faceted=True)
    issuer_name = indexes.CharField(model_attr="historical_item__issuer", faceted=True)
    named_beneficiary = indexes.CharField(model_attr="historical_item__named_beneficiary", faceted=True)

    def prepare_number_of_images(self, obj):
        return obj.images.count()

    def prepare_catalogue_numbers(self, obj):
        return obj.historical_item.get_catalogue_numbers_display()

    class Meta:
        model = ItemPart
        fields = [
            "id",
            "text",
            "repository_city",
            "repository_name",
            "shelfmark",
            "catalogue_numbers",
            "date",
            "type",
            "number_of_images",
            "issuer_name",
        ]

    def get_model(self):
        return ItemPart
