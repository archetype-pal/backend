from django.contrib.auth import get_user_model
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from apps.common.views import BasePrivilegedViewSet

from .serializers import UserListManagementSerializer, UserSerializer, UserWriteManagementSerializer

User = get_user_model()


class UserProfileView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class UserManagementViewSet(BasePrivilegedViewSet):
    queryset = User.objects.all().order_by("-date_joined")

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserWriteManagementSerializer
        return UserListManagementSerializer
