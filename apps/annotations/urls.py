from rest_framework.routers import DefaultRouter

from .views import GraphComponentManagementViewSet, GraphManagementViewSet, GraphViewSet, GraphViewerWriteViewSet

router = DefaultRouter()
router.register("manuscripts/graphs", GraphViewSet, basename="manuscripts-graphs")
router.register("annotations/graphs", GraphViewerWriteViewSet, basename="annotations-graphs")
router.register("management/annotations/graphs", GraphManagementViewSet, basename="management-graphs")
router.register(
    "management/annotations/graph-components",
    GraphComponentManagementViewSet,
    basename="management-graph-components",
)

urlpatterns = router.urls
