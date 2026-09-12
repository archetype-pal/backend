from typing import Any

from rest_framework import serializers

from apps.manuscripts.models import ItemPart
from apps.uploads.models import ImageUploadSession


class ImageUploadSessionCreateSerializer(serializers.Serializer):
    """Shape validation only — path safety, collisions and disk preflight are
    the application service's job (no write logic in serializers)."""

    item_part = serializers.PrimaryKeyRelatedField(queryset=ItemPart.objects.all())
    filename = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)
    locus = serializers.CharField(required=False, allow_blank=True, default="", max_length=72)
    tags = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    subfolder = serializers.CharField(required=False, allow_blank=True, default="", max_length=120)


class ImageUploadSessionSerializer(serializers.ModelSerializer):
    total_chunks = serializers.IntegerField(read_only=True)
    missing_chunks = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()

    class Meta:
        model = ImageUploadSession
        fields = [
            "id",
            "status",
            "error",
            "item_part",
            "original_filename",
            "declared_size",
            "chunk_size",
            "total_chunks",
            "received_chunks",
            "missing_chunks",
            "destination_path",
            "locus",
            "tags",
            "item_image",
            "task_id",
            "task",
            "created",
            "modified",
        ]
        read_only_fields = fields

    def get_missing_chunks(self, session: ImageUploadSession) -> list[int]:
        return session.missing_chunks()

    def get_task(self, session: ImageUploadSession) -> dict[str, Any] | None:
        if not session.task_id:
            return None
        # Same AsyncResult wrapper the search management UI polls, so the
        # frontend's task-status contract is identical. Accessing the result
        # backend can itself fail (e.g. Redis unreachable) — a session GET
        # must degrade, not 500.
        from apps.search.admin_service import SearchAdminService

        try:
            return SearchAdminService().task_status(session.task_id)
        except Exception:
            return {
                "task_id": session.task_id,
                "state": "UNKNOWN",
                "progress": None,
                "result": None,
                "error": "Task status unavailable (result backend unreachable).",
            }
