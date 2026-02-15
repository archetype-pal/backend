from rest_framework.routers import DefaultRouter

from .admin_views import (
    AllographAdminViewSet,
    AllographComponentAdminViewSet,
    AllographComponentFeatureAdminViewSet,
    CharacterAdminViewSet,
    ComponentAdminViewSet,
    FeatureAdminViewSet,
    PositionAdminViewSet,
)

router = DefaultRouter()
router.register("symbols/characters", CharacterAdminViewSet, basename="admin-characters")
router.register("symbols/allographs", AllographAdminViewSet, basename="admin-allographs")
router.register("symbols/components", ComponentAdminViewSet, basename="admin-components")
router.register("symbols/features", FeatureAdminViewSet, basename="admin-features")
router.register("symbols/positions", PositionAdminViewSet, basename="admin-positions")
router.register(
    "symbols/allograph-components",
    AllographComponentAdminViewSet,
    basename="admin-allograph-components",
)
router.register(
    "symbols/allograph-component-features",
    AllographComponentFeatureAdminViewSet,
    basename="admin-allograph-component-features",
)

urlpatterns = router.urls
