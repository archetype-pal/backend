from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from rest_framework import serializers

from .services import UserWriteService

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


class UserListManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_active",
            "date_joined",
            "last_login",
        ]


class UserWriteManagementSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_active",
            "password",
        ]

    def validate_password(self, value):
        if value:
            return make_password(value)
        return value

    @staticmethod
    def _service() -> UserWriteService:
        return UserWriteService()

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        return self._service().create_user(user_data=validated_data, password=password)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        return self._service().update_user(user=instance, user_data=validated_data, password=password)
