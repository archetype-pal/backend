from django.contrib.auth import get_user_model

from apps.common.api.base_admin_views import BaseAdminViewSet

from .admin_serializers import UserListAdminSerializer, UserWriteAdminSerializer

User = get_user_model()


class UserAdminViewSet(BaseAdminViewSet):
    queryset = User.objects.all().order_by("-date_joined")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserWriteAdminSerializer
        return UserListAdminSerializer
