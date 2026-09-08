from rest_framework import serializers

from .models import AgentRun, ServiceIdentity


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)


class AgentRunSerializer(serializers.ModelSerializer):
    """What the requester gets back.

    `cost_micros` and `requester_key` are deliberately absent: what a question
    cost the programme is an operator's business, and echoing back the key a
    requester was bucketed under invites probing it.
    """

    class Meta:
        model = AgentRun
        fields = ("id", "question", "answer", "citations", "turns", "status", "error", "created")
        read_only_fields = fields


class AgentRunManagementSerializer(serializers.ModelSerializer):
    identity_slug = serializers.CharField(source="identity.slug", read_only=True)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "identity",
            "identity_slug",
            "actor",
            "requester_key",
            "question",
            "answer",
            "citations",
            "tool_calls",
            "turns",
            "status",
            "error",
            "cost_micros",
            "created",
        )
        read_only_fields = fields


class ServiceIdentitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceIdentity
        fields = (
            "id",
            "slug",
            "description",
            "allowed_tools",
            "daily_run_quota",
            "max_turns",
            "model_name",
            "enabled",
            "created",
        )
