from rest_framework.routers import DefaultRouter

from .admin_views import (
    BibliographicSourceAdminViewSet,
    CatalogueNumberAdminViewSet,
    CurrentItemAdminViewSet,
    HistoricalItemAdminViewSet,
    HistoricalItemDescriptionAdminViewSet,
    ImageTextAdminViewSet,
    ItemFormatAdminViewSet,
    ItemImageAdminViewSet,
    ItemPartAdminViewSet,
    RepositoryAdminViewSet,
)

router = DefaultRouter()
router.register(
    "manuscripts/historical-items", HistoricalItemAdminViewSet, basename="admin-historical-items"
)
router.register("manuscripts/item-parts", ItemPartAdminViewSet, basename="admin-item-parts")
router.register("manuscripts/item-images", ItemImageAdminViewSet, basename="admin-item-images")
router.register("manuscripts/image-texts", ImageTextAdminViewSet, basename="admin-image-texts")
router.register(
    "manuscripts/catalogue-numbers",
    CatalogueNumberAdminViewSet,
    basename="admin-catalogue-numbers",
)
router.register(
    "manuscripts/descriptions",
    HistoricalItemDescriptionAdminViewSet,
    basename="admin-descriptions",
)
router.register("manuscripts/repositories", RepositoryAdminViewSet, basename="admin-repositories")
router.register(
    "manuscripts/current-items", CurrentItemAdminViewSet, basename="admin-current-items"
)
router.register(
    "manuscripts/sources", BibliographicSourceAdminViewSet, basename="admin-sources"
)
router.register("manuscripts/formats", ItemFormatAdminViewSet, basename="admin-formats")

urlpatterns = router.urls
