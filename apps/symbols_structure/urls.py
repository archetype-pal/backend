from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AllographListView,
    CharacterManagementViewSet,
    ComponentManagementViewSet,
    FeatureManagementViewSet,
    PositionListView,
    PositionManagementViewSet,
)

router = SimpleRouter()
router.register("management/symbols/characters", CharacterManagementViewSet, basename="management-characters")
router.register("management/symbols/components", ComponentManagementViewSet, basename="management-components")
router.register("management/symbols/features", FeatureManagementViewSet, basename="management-features")
router.register("management/symbols/positions", PositionManagementViewSet, basename="management-positions")

urlpatterns = router.urls + [
    path("allographs/", AllographListView.as_view(), name="allograph-list"),
    path("positions/", PositionListView.as_view(), name="position-list"),
]
