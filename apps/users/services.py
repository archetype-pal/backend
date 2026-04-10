"""Application services for users app workflows."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser

User = get_user_model()


class UserWriteService:
    """Orchestrate management-side user create/update workflows."""

    def create_user(self, *, user_data: dict[str, Any], password: str | None) -> AbstractBaseUser:
        user: AbstractBaseUser = User(**user_data)
        if password:
            user.password = password
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update_user(
        self, *, user: AbstractBaseUser, user_data: dict[str, Any], password: str | None
    ) -> AbstractBaseUser:
        for attr, value in user_data.items():
            setattr(user, attr, value)
        if password:
            user.password = password
        user.save()
        return user
