from rest_framework import serializers

from apps.search.admin_service import ACTIONS, PER_INDEX_ACTIONS
from apps.search.types import IndexType


class SearchActionSerializer(serializers.Serializer):
    """The body of `POST /search/management/actions/`: a known action, plus an index for the per-index ones."""

    action = serializers.ChoiceField(choices=sorted(ACTIONS))
    index_type = serializers.ChoiceField(choices=IndexType.segments(), required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if attrs["action"] in PER_INDEX_ACTIONS and not attrs["index_type"]:
            raise serializers.ValidationError(
                {"index_type": f"'index_type' is required for action '{attrs['action']}'."}
            )
        return attrs
