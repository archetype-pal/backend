from django.contrib.auth import get_user_model
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import SimpleRateThrottle

from apps.common.views import ActionSerializerMixin, BasePrivilegedViewSet

from .serializers import UserListManagementSerializer, UserSerializer, UserWriteManagementSerializer

User = get_user_model()


class LoginThrottle(SimpleRateThrottle):
    scope = "login"
    rate = "10/min"  # hardcoded: DEFAULT_THROTTLE_RATES is {} under DEBUG

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class UserProfileView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class UserManagementViewSet(ActionSerializerMixin, BasePrivilegedViewSet):
    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = UserListManagementSerializer
    action_serializer_classes = {
        "create": UserWriteManagementSerializer,
        "update": UserWriteManagementSerializer,
        "partial_update": UserWriteManagementSerializer,
    }
