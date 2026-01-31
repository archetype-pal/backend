"""Serializers for search API. Map DTOs to JSON."""

from rest_framework import serializers


class SearchResultSerializer(serializers.Serializer):
    """Serialize SearchResult (list response)."""

    results = serializers.ListField(child=serializers.DictField())
    total = serializers.IntegerField()
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()


class FacetResultSerializer(serializers.Serializer):
    """Serialize FacetResult (Meilisearch-native shape)."""

    facetDistribution = serializers.DictField(
        child=serializers.DictField(child=serializers.IntegerField()),
        source="facet_distribution",
    )
    facetStats = serializers.DictField(
        child=serializers.DictField(child=serializers.FloatField()),
        source="facet_stats",
        required=False,
    )
