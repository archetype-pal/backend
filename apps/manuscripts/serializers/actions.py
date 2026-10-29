"""Input serializers for the image-text editorial actions (transition, region links, HTR import, bulk)."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.common.serializers import StrictCharField
from apps.manuscripts.models import ImageText


class TeiContentSerializer(serializers.Serializer):
    content = StrictCharField(allow_blank=True)


class TransitionSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=ImageText.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    # Only meaningful when sending to Review; validated up front so a bad id is a 400, not a FK 500.
    assignee = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), required=False, allow_null=True
    )


class LinkRegionSerializer(serializers.Serializer):
    """A new region (`geometry`) or an existing TEXT graph of the image (`graph_id`)."""

    element_index = serializers.IntegerField(min_value=0)
    graph_id = serializers.IntegerField(required=False)
    geometry = serializers.DictField(required=False)

    def validate(self, attrs):
        if "graph_id" not in attrs and "geometry" not in attrs:
            raise serializers.ValidationError({"detail": "geometry (GeoJSON) or graph_id is required."})
        return attrs


class UnlinkRegionSerializer(serializers.Serializer):
    graph_id = serializers.IntegerField()


class UnlinkElementSerializer(UnlinkRegionSerializer):
    element_index = serializers.IntegerField(min_value=0)


class ImportHtrSerializer(serializers.Serializer):
    # An IntegerField, not a related field: an unknown image is a 404 from the service.
    item_image = serializers.IntegerField()
    format = serializers.ChoiceField(choices=["page", "alto"])
    xml = serializers.CharField()
    type = serializers.ChoiceField(choices=ImageText.Type.choices, default=ImageText.Type.TRANSCRIPTION)
    language = serializers.CharField(required=False, allow_blank=True, default="")


class BulkActionSerializer(serializers.Serializer):
    """`transition` (payload: to_status, note?), `set_language` (payload: language) or `delete`."""

    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)
    action = serializers.ChoiceField(choices=["transition", "set_language", "delete"])
    payload = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        payload = attrs["payload"]
        if attrs["action"] == "transition":
            if payload.get("to_status") not in ImageText.Status.values:
                raise serializers.ValidationError({"detail": "Unknown status."})
        elif attrs["action"] == "set_language" and "language" not in payload:
            raise serializers.ValidationError({"detail": "`language` is required."})
        return attrs


class ImageTextUpsertSerializer(serializers.ModelSerializer):
    """Body of the per-image "sole text" PUT; the image and kind come from the URL."""

    class Meta:
        model = ImageText
        fields = ["content", "status", "language"]
        # PUT replaces the whole text, so an omitted field means "empty", not "keep".
        extra_kwargs = {
            "content": {"default": ""},
            "language": {"default": ""},
            "status": {"default": ImageText.Status.DRAFT},
        }
