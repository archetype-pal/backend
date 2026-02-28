"""Application services for users app workflows."""

from typing import Any

from django.contrib.auth import get_user_model

User = get_user_model()


class UserWriteService:
    """Orchestrate management-side user create/update workflows."""

    def create_user(self, *, user_data: dict[str, Any], password: str | None) -> Any:
        user = User(**user_data)
        if password:
            user.password = password
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update_user(self, *, user: Any, user_data: dict[str, Any], password: str | None) -> Any:
        for attr, value in user_data.items():
            setattr(user, attr, value)
        if password:
            user.password = password
        user.save()
        return user
