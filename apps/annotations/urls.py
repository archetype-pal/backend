from rest_framework.routers import SimpleRouter

from .views import GraphManagementViewSet, GraphViewerWriteViewSet, GraphViewSet

router = SimpleRouter()
router.register("manuscripts/graphs", GraphViewSet, basename="manuscripts-graphs")
router.register("annotations/graphs", GraphViewerWriteViewSet, basename="annotations-graphs")
router.register("management/annotations/graphs", GraphManagementViewSet, basename="management-graphs")

urlpatterns = router.urls
