from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    HandItemImagesForManagement,
    HandManagementViewSet,
    HandViewSet,
    ScribeManagementViewSet,
    ScribeViewSet,
    ScriptManagementViewSet,
)

router = DefaultRouter()
router.register("scribes", ScribeViewSet)
router.register("hands", HandViewSet)
router.register("management/scribes/scribes", ScribeManagementViewSet, basename="management-scribes")
router.register("management/scribes/hands", HandManagementViewSet, basename="management-hands")
router.register("management/scribes/scripts", ScriptManagementViewSet, basename="management-scripts")


urlpatterns = router.urls + [
    path("management/scribes/get_item_images/", HandItemImagesForManagement.as_view(), name="get_item_images"),
]
