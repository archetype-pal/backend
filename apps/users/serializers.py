from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Full user profile — used for auth/profile responses."""

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "username", "email", "is_staff"]


class UserSummarySerializer(serializers.ModelSerializer):
    """Lightweight user representation — embedded in other resources (e.g. author)."""

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]
