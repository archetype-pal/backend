from typing import Any

from rest_framework import serializers

from apps.manuscripts.models import ItemPart
from apps.uploads.models import UploadSession


class UploadSessionCreateSerializer(serializers.Serializer):
    """Shape validation only — path safety, collisions and disk preflight are
    the application service's job (no write logic in serializers)."""

    item_part = serializers.PrimaryKeyRelatedField(queryset=ItemPart.objects.all())
    filename = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)
    sha256 = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)
    locus = serializers.CharField(required=False, allow_blank=True, default="", max_length=72)
    tags = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    subfolder = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)


class UploadSessionSerializer(serializers.ModelSerializer):
    total_chunks = serializers.IntegerField(read_only=True)
    missing_chunks = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()

    class Meta:
        model = UploadSession
        fields = [
            "id",
            "status",
            "error",
            "item_part",
            "original_filename",
            "declared_size",
            "declared_sha256",
            "computed_sha256",
            "chunk_size",
            "total_chunks",
            "received_chunks",
            "missing_chunks",
            "destination_path",
            "subfolder",
            "locus",
            "tags",
            "item_image",
            "task_id",
            "task",
            "created",
            "modified",
        ]
        read_only_fields = fields

    def get_missing_chunks(self, session: UploadSession) -> list[int]:
        return session.missing_chunks()

    def get_task(self, session: UploadSession) -> dict[str, Any] | None:
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
