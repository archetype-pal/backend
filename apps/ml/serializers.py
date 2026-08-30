from rest_framework import serializers

from .models import MLJob, MLJobTarget


class MLJobTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MLJobTarget
        fields = ("target_type", "target_id")


class MLJobListSerializer(serializers.ModelSerializer):
    class Meta:
        model = MLJob
        fields = (
            "id",
            "task",
            "provider",
            "model_name",
            "model_version",
            "status",
            "cost_micros",
            "cost_currency",
            "duration_ms",
            "created",
        )


class MLJobSerializer(serializers.ModelSerializer):
    targets = MLJobTargetSerializer(many=True, read_only=True)
    actor_username = serializers.CharField(source="actor.username", read_only=True, default="")

    class Meta:
        model = MLJob
        fields = (
            "id",
            "task",
            "provider",
            "model_name",
            "model_version",
            "prompt_hash",
            "input_ref",
            "params",
            "status",
            "error",
            "input_tokens",
            "output_tokens",
            "cost_micros",
            "cost_currency",
            "actor",
            "actor_username",
            "celery_task_id",
            "duration_ms",
            "created",
            "targets",
        )
