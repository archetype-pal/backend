from rest_framework import serializers


class SearchResultSerializer(serializers.Serializer):
    results = serializers.ListField(child=serializers.DictField())
    total = serializers.IntegerField()
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()


class FacetResultSerializer(serializers.Serializer):
    facetDistribution = serializers.DictField(
        child=serializers.DictField(child=serializers.IntegerField()),
        source="facet_distribution",
    )
    facetStats = serializers.DictField(
        child=serializers.DictField(child=serializers.FloatField()),
        source="facet_stats",
        required=False,
    )
