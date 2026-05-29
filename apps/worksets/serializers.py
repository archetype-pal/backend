import json

from rest_framework import serializers

from apps.users.serializers import UserSummarySerializer

from .models import Workset

# Worksets persist a denormalized client payload; cap it so a runaway lightbox
# (or abuse) can't store unbounded JSON blobs.
MAX_PAYLOAD_BYTES = 256 * 1024
# `description` is free text on an anonymously-citable model; bound it too so it
# can't be used to store/serve unbounded blobs (the payload cap alone would
# leave this field as an open back door).
MAX_DESCRIPTION_CHARS = 4000


class WorksetListSerializer(serializers.ModelSerializer):
    """Lightweight listing — no payload, just metadata."""

    class Meta:
        model = Workset
        fields = ["public_id", "title", "description", "visibility", "created_at", "updated_at"]


class WorksetDetailSerializer(serializers.ModelSerializer):
    """Full record (incl. payload) used for retrieve/create/update."""

    owner = UserSummarySerializer(read_only=True)

    class Meta:
        model = Workset
        fields = [
            "public_id",
            "title",
            "description",
            "visibility",
            "payload",
            "owner",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["public_id", "owner", "created_at", "updated_at"]

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("payload must be a JSON object.")
        size = len(json.dumps(value).encode("utf-8"))
        if size > MAX_PAYLOAD_BYTES:
            raise serializers.ValidationError(f"payload exceeds the maximum size of {MAX_PAYLOAD_BYTES // 1024} KB.")
        return value

    def validate_description(self, value):
        if value and len(value) > MAX_DESCRIPTION_CHARS:
            raise serializers.ValidationError(
                f"description exceeds the maximum length of {MAX_DESCRIPTION_CHARS} characters."
            )
        return value
