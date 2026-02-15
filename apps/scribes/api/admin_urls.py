from rest_framework.routers import DefaultRouter

from .admin_views import HandAdminViewSet, ScribeAdminViewSet, ScriptAdminViewSet

router = DefaultRouter()
router.register("scribes/scribes", ScribeAdminViewSet, basename="admin-scribes")
router.register("scribes/hands", HandAdminViewSet, basename="admin-hands")
router.register("scribes/scripts", ScriptAdminViewSet, basename="admin-scripts")

urlpatterns = router.urls
