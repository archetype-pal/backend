from rest_framework.routers import SimpleRouter

from .views import (
    HandDescriptionManagementViewSet,
    HandManagementViewSet,
    HandViewSet,
    ScribeManagementViewSet,
    ScribeViewSet,
    ScriptManagementViewSet,
)

router = SimpleRouter()
router.register("scribes", ScribeViewSet)
router.register("hands", HandViewSet)
router.register("management/scribes/scribes", ScribeManagementViewSet, basename="management-scribes")
router.register("management/scribes/hands", HandManagementViewSet, basename="management-hands")
router.register(
    "management/scribes/hand-descriptions",
    HandDescriptionManagementViewSet,
    basename="management-hand-descriptions",
)
router.register("management/scribes/scripts", ScriptManagementViewSet, basename="management-scripts")


urlpatterns = router.urls + []
