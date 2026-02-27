from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AllographComponentFeatureManagementViewSet,
    AllographComponentManagementViewSet,
    AllographListView,
    AllographManagementViewSet,
    CharacterManagementViewSet,
    ComponentManagementViewSet,
    FeatureManagementViewSet,
    PositionListView,
    PositionManagementViewSet,
)

router = DefaultRouter()
router.register("management/symbols/characters", CharacterManagementViewSet, basename="management-characters")
router.register("management/symbols/allographs", AllographManagementViewSet, basename="management-allographs")
router.register("management/symbols/components", ComponentManagementViewSet, basename="management-components")
router.register("management/symbols/features", FeatureManagementViewSet, basename="management-features")
router.register("management/symbols/positions", PositionManagementViewSet, basename="management-positions")
router.register(
    "management/symbols/allograph-components",
    AllographComponentManagementViewSet,
    basename="management-allograph-components",
)
router.register(
    "management/symbols/allograph-component-features",
    AllographComponentFeatureManagementViewSet,
    basename="management-allograph-component-features",
)

urlpatterns = router.urls + [
    path("allographs/", AllographListView.as_view(), name="allograph-list"),
    path("positions/", PositionListView.as_view(), name="allograph-list"),
]
