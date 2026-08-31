from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ImpersonationToken


class ImpersonationTokenAuthentication(TokenAuthentication):
    """Resolve impersonation tokens, falling back to ordinary auth tokens.

    Marks the returned user so anything reading ``request.user`` — the audit
    log, the profile endpoint — can tell an impersonated session from a real one.
    """

    def authenticate_credentials(self, key):
        token = ImpersonationToken.objects.select_related("user", "impersonated_by").filter(pk=key).first()
        if token is None:
            return super().authenticate_credentials(key)
        if token.expires <= timezone.now():
            raise AuthenticationFailed("Impersonation session expired.")
        if not token.user.is_active:
            raise AuthenticationFailed("User inactive or deleted.")
        token.user.impersonated_by = token.impersonated_by
        return (token.user, token)
