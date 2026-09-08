from django.urls import path
from rest_framework import routers

from .views import AgentRunManagementViewSet, AgentToolsView, AskView, ServiceIdentityManagementViewSet

router = routers.DefaultRouter()
router.register("management/agent-identities", ServiceIdentityManagementViewSet, basename="agent-identities")
router.register("management/agent-runs", AgentRunManagementViewSet, basename="agent-runs")

urlpatterns = [
    path("agent/ask/", AskView.as_view(), name="agent-ask"),
    path("agent/tools/", AgentToolsView.as_view(), name="agent-tools"),
    *router.urls,
]
