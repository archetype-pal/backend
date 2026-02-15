from rest_framework.routers import DefaultRouter

from .admin_views import GraphAdminViewSet, GraphComponentAdminViewSet

router = DefaultRouter()
router.register("annotations/graphs", GraphAdminViewSet, basename="admin-graphs")
router.register(
    "annotations/graph-components",
    GraphComponentAdminViewSet,
    basename="admin-graph-components",
)

urlpatterns = router.urls
