from rest_framework import serializers


class SearchActionSerializer(serializers.Serializer):
    """`action` names are validated by `SearchAdminService.start_action`, which owns the list."""

    action = serializers.CharField()
    index_type = serializers.CharField(required=False, allow_null=True, default=None)
