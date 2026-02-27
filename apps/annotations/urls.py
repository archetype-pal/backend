from rest_framework.routers import DefaultRouter

from .views import GraphComponentManagementViewSet, GraphManagementViewSet, GraphViewSet

router = DefaultRouter()
router.register("manuscripts/graphs", GraphViewSet, basename="manuscripts-graphs")
router.register("management/annotations/graphs", GraphManagementViewSet, basename="management-graphs")
router.register(
    "management/annotations/graph-components",
    GraphComponentManagementViewSet,
    basename="management-graph-components",
)

urlpatterns = router.urls
