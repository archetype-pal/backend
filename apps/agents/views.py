"""The public agent endpoint, and the operator's view of what it did.

`ask` is a POST that anyone may call, so it is the widest attack surface the
programme adds. Three things narrow it, in order: the DRF throttle bucket, the
per-requester daily quota, and the shared spend cap in `apps.ml`. Each catches
something the others do not — a burst, a persistent single caller, and the
aggregate bill.
"""

import hashlib

from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.agents import services, tools
from apps.agents.models import AgentRun, ServiceIdentity
from apps.agents.serializers import (
    AgentRunManagementSerializer,
    AgentRunSerializer,
    AskSerializer,
    ServiceIdentitySerializer,
)
from apps.common.permissions import IsSuperuser


class AgentThrottle(UserRateThrottle):
    """One bucket, keyed by account when signed in and by address when not.

    `UserRateThrottle` alone rather than paired with `AnonRateThrottle`: for an
    anonymous caller both fall back to the same address-derived key, so pairing
    them charges every request twice and halves the advertised rate.

    The rate is read from settings directly instead of DRF's scope table, which
    is empty under DEBUG — and a throttle that raises `ImproperlyConfigured`
    takes the endpoint down rather than protecting it. Off under DEBUG, like the
    site-wide throttles; the quota and the spend cap still apply there, and they
    are the limits that cost money.
    """

    scope = "agent"

    def get_rate(self):
        from django.conf import settings

        if settings.DEBUG:
            return None
        return getattr(settings, "DRF_THROTTLE_AGENT_RATE", "") or None


def requester_key(request) -> str:
    """A stable, coarse bucket for an anonymous requester.

    A salted digest rather than the address itself: the quota needs to tell two
    requesters apart, which does not require knowing who either of them is, and
    a log of every question asked of a public research tool alongside the IP
    that asked it is more personal data than the feature is worth.
    """
    from django.conf import settings

    address = request.META.get("REMOTE_ADDR", "") or ""
    digest = hashlib.sha256(f"{settings.SECRET_KEY}:{address}".encode()).hexdigest()
    return digest[:32]


class AskView(APIView):
    """POST a question, get an answer with verified citations."""

    permission_classes = [AllowAny]
    throttle_classes = [AgentThrottle]
    serializer_class = AskSerializer

    def post(self, request):
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            run = services.ask(
                serializer.validated_data["question"],
                actor=request.user,
                requester_key=requester_key(request),
            )
        except services.AgentError as exc:
            # 503 rather than 400: every AgentError is the service declining —
            # disabled, out of quota, no usable tools — not a malformed request.
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(AgentRunSerializer(run).data)


class AgentToolsView(APIView):
    """What the public agent can currently do, and why it cannot do the rest.

    Public on purpose. §11 commits the programme to publishing its limits, and
    an agent that silently lacks hand comparison looks the same to a visitor as
    one that has it and found nothing.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        identity = ServiceIdentity.objects.filter(slug=services.DEFAULT_IDENTITY).first()
        allowed = set(identity.allowed_tools or []) if identity else set()
        return Response(
            {
                "identity": services.DEFAULT_IDENTITY,
                "enabled": bool(identity and identity.enabled),
                "tools": [
                    {
                        "name": name,
                        "description": tool.description,
                        "granted": name in allowed,
                        "available": not tool.unavailable(),
                        "unavailable_reason": tool.unavailable(),
                    }
                    for name, tool in sorted(tools.TOOL_REGISTRY.items())
                ],
            }
        )


class ServiceIdentityManagementViewSet(viewsets.ModelViewSet):
    """Superuser-only. Editing an identity is editing a credential's scope."""

    permission_classes = [IsSuperuser]
    queryset = ServiceIdentity.objects.all()
    serializer_class = ServiceIdentitySerializer


class AgentRunManagementViewSet(viewsets.ReadOnlyModelViewSet):
    """The full log, including what each run was asked and what it called.

    Read-only: this is the record that makes an injection attempt findable after
    the fact, and a record that can be edited is not one.
    """

    permission_classes = [IsSuperuser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["identity", "status", "actor"]
    queryset = AgentRun.objects.select_related("identity", "actor")
    serializer_class = AgentRunManagementSerializer
