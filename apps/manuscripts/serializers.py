from rest_framework import serializers

from .models import CatalogueNumber, CurrentItem, HistoricalItem, HistoricalItemDescription, ImageText, ItemImage, ItemPart, Repository


class RepositorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Repository
        fields = ["name", "label", "place", "url"]


class CurrentItemSerializer(serializers.ModelSerializer):
    repository = RepositorySerializer()

    class Meta:
        model = CurrentItem
        fields = ["repository", "shelfmark"]


class CatalogueNumberSerializer(serializers.ModelSerializer):
    catalogue = RepositorySerializer()

    class Meta:
        model = CatalogueNumber
        fields = ["number", "url", "catalogue"]


class HistoricalItemDescriptionSerializer(serializers.ModelSerializer):
    source = RepositorySerializer()

    class Meta:
        model = HistoricalItemDescription
        fields = ["source", "content"]


class HistoricalItemSerializer(serializers.ModelSerializer):
    catalogue_numbers = CatalogueNumberSerializer(many=True)
    descriptions = HistoricalItemDescriptionSerializer(many=True)

    class Meta:
        model = HistoricalItem
        fields = [
            "type",
            "format",
            "date",
            "catalogue_numbers",
            "descriptions",
            # "language",
            # "vernacular",
            # "neumed",
            # "hair_type",
            # "issuer",
            # "named_beneficiary",
        ]


class ItemPartDetailSerializer(serializers.ModelSerializer):
    current_item = CurrentItemSerializer()
    historical_item = HistoricalItemSerializer()

    class Meta:
        model = ItemPart
        fields = ["id", "current_item", "historical_item"]


class ItemPartListSerializer(serializers.ModelSerializer):
    # Fields from HistoricalItem
    type = serializers.CharField(source="historical_item.type")
    format = serializers.CharField(source="historical_item.format")
    language = serializers.CharField(source="historical_item.language")
    vernacular = serializers.BooleanField(source="historical_item.vernacular")
    neumed = serializers.BooleanField(source="historical_item.neumed")
    hair_type = serializers.CharField(source="historical_item.hair_type")
    date = serializers.CharField(source="historical_item.date")
    issuer = serializers.CharField(source="historical_item.issuer")
    named_beneficiary = serializers.CharField(source="historical_item.named_beneficiary")

    # Fields from CurrentItem
    repository_id = serializers.IntegerField(source="current_item.repository_id")
    shelfmark = serializers.CharField(source="current_item.shelfmark")

    class Meta:
        model = ItemPart
        fields = [
            "id",
            "type",
            "format",
            "language",
            "vernacular",
            "neumed",
            "hair_type",
            "date",
            "issuer",
            "named_beneficiary",
            "repository_id",
            "shelfmark",
        ]


class ImageTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageText
        fields = ["type", "content"]


class ImageSerializer(serializers.ModelSerializer):
    texts = ImageTextSerializer(many=True)
    iiif_image = serializers.URLField(source="image.iiif.identifier")

    class Meta:
        model = ItemImage
        fields = ["id", "iiif_image", "locus", "number_of_annotations", "texts"]
