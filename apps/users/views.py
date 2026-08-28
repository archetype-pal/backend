from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.common.views import ActionSerializerMixin, BasePrivilegedViewSet

from .serializers import UserListManagementSerializer, UserSerializer, UserWriteManagementSerializer
from .services import impersonate_user

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


class TokenLogoutView(APIView):
    """Revoke only the presented credential.

    Replaces djoser's `TokenDestroyView`, which deletes `request.user`'s own
    token — during an impersonated session that is the *target's*. This also
    makes logout the "stop impersonating" control.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserManagementViewSet(ActionSerializerMixin, BasePrivilegedViewSet):
    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = UserListManagementSerializer
    action_serializer_classes = {
        "create": UserWriteManagementSerializer,
        "update": UserWriteManagementSerializer,
        "partial_update": UserWriteManagementSerializer,
    }

    @action(detail=True, methods=["post"])
    def impersonate(self, request: Request, pk: str | None = None) -> Response:
        """Mint a short-lived impersonation credential for the target user.

        Superuser-only (inherited from `BasePrivilegedViewSet`). The caller
        swaps its stored auth token for the one returned here to browse the
        app as the target user; see `apps.users.services.impersonate_user`
        for the safety checks and audit logging.
        """
        target = self.get_object()
        token = impersonate_user(actor=request.user, target=target)
        return Response({"auth_token": token.key})
